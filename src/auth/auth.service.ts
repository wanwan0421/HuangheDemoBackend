import { BadRequestException, Injectable, UnauthorizedException } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { ConfigService } from '@nestjs/config';
import { Model, Types } from 'mongoose';
import { createHmac, pbkdf2Sync, randomBytes, timingSafeEqual } from 'crypto';
import { User, UserDocument } from './schemas/user.schema';
import { RefreshToken, RefreshTokenDocument } from './schemas/refresh-token.schema';

type AuthUser = {
  id: string;
  username: string;
  email: string;
  favoriteModels?: Record<string, any>[];
  favoriteData?: Record<string, any>[];
  simulationResults?: Record<string, any>[];
};

type TokenBundle = {
  accessToken: string;
  refreshToken: string;
};

@Injectable()
export class AuthService {
  private readonly accessTokenTtlSeconds: number;
  private readonly refreshTokenTtlSeconds: number;
  private readonly accessSecret: string;

  constructor(
    @InjectModel(User.name)
    private readonly userModel: Model<UserDocument>,
    @InjectModel(RefreshToken.name)
    private readonly refreshTokenModel: Model<RefreshTokenDocument>,
    private readonly configService: ConfigService,
  ) {
    this.accessTokenTtlSeconds = Number(this.configService.get('AUTH_ACCESS_TTL_SECONDS') || 30 * 60);
    this.refreshTokenTtlSeconds = Number(this.configService.get('AUTH_REFRESH_TTL_SECONDS') || 15 * 24 * 60 * 60);
    this.accessSecret = this.configService.get<string>('AUTH_ACCESS_SECRET') || 'replace-this-access-secret';
  }

  private sanitizeUser(user: UserDocument): AuthUser {
    return {
      id: String(user._id),
      username: user.username,
      email: user.email,
      favoriteModels: Array.isArray((user as any).favoriteModels) ? (user as any).favoriteModels : [],
      favoriteData: Array.isArray((user as any).favoriteData) ? (user as any).favoriteData : [],
      simulationResults: Array.isArray((user as any).simulationResults) ? (user as any).simulationResults : [],
    };
  }

  private hashPassword(password: string): string {
    const salt = randomBytes(16).toString('hex');
    const digest = pbkdf2Sync(password, salt, 120000, 64, 'sha512').toString('hex');
    return `pbkdf2$${salt}$${digest}`;
  }

  private verifyPassword(password: string, storedHash: string): boolean {
    const [algo, salt, digest] = storedHash.split('$');
    if (algo !== 'pbkdf2' || !salt || !digest) {
      return false;
    }

    const derived = pbkdf2Sync(password, salt, 120000, 64, 'sha512').toString('hex');
    const a = Buffer.from(derived, 'hex');
    const b = Buffer.from(digest, 'hex');

    if (a.length !== b.length) {
      return false;
    }

    return timingSafeEqual(a, b);
  }

  private base64Url(input: string): string {
    return Buffer.from(input, 'utf8')
      .toString('base64')
      .replace(/=/g, '')
      .replace(/\+/g, '-')
      .replace(/\//g, '_');
  }

  private signAccessToken(user: AuthUser): string {
    const now = Math.floor(Date.now() / 1000);
    const payload = {
      sub: user.id,
      email: user.email,
      username: user.username,
      iat: now,
      exp: now + this.accessTokenTtlSeconds,
    };

    const encodedPayload = this.base64Url(JSON.stringify(payload));
    const signature = createHmac('sha256', this.accessSecret)
      .update(encodedPayload)
      .digest('base64')
      .replace(/=/g, '')
      .replace(/\+/g, '-')
      .replace(/\//g, '_');

    return `${encodedPayload}.${signature}`;
  }

  private verifyAccessToken(token: string): { sub: string; email: string; username: string; exp: number } {
    const parts = token.split('.');
    if (parts.length !== 2) {
      throw new UnauthorizedException('AUTH_UNAUTHORIZED');
    }

    const [encodedPayload, signature] = parts;
    const expectedSignature = createHmac('sha256', this.accessSecret)
      .update(encodedPayload)
      .digest('base64')
      .replace(/=/g, '')
      .replace(/\+/g, '-')
      .replace(/\//g, '_');

    const a = Buffer.from(signature);
    const b = Buffer.from(expectedSignature);
    if (a.length !== b.length || !timingSafeEqual(a, b)) {
      throw new UnauthorizedException('AUTH_UNAUTHORIZED');
    }

    let payload: any;
    try {
      const base64 = encodedPayload.replace(/-/g, '+').replace(/_/g, '/');
      const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
      payload = JSON.parse(Buffer.from(padded, 'base64').toString('utf8'));
    } catch {
      throw new UnauthorizedException('AUTH_UNAUTHORIZED');
    }

    const now = Math.floor(Date.now() / 1000);
    if (!payload?.sub || !payload?.exp || payload.exp < now) {
      throw new UnauthorizedException('AUTH_UNAUTHORIZED');
    }

    return payload;
  }

  private hashRefreshToken(token: string): string {
    return createHmac('sha256', this.accessSecret).update(token).digest('hex');
  }

  private async issueTokenBundle(
    user: UserDocument,
    userAgent?: string,
    ip?: string,
  ): Promise<TokenBundle> {
    const refreshToken = randomBytes(48).toString('hex');
    const refreshTokenHash = this.hashRefreshToken(refreshToken);
    const expiresAt = new Date(Date.now() + this.refreshTokenTtlSeconds * 1000);

    await this.refreshTokenModel.create({
      userId: user._id,
      refreshTokenHash,
      expiresAt,
      revokedAt: null,
      userAgent: userAgent || '',
      ip: ip || '',
    });

    const authUser = this.sanitizeUser(user);
    const accessToken = this.signAccessToken(authUser);

    return { accessToken, refreshToken };
  }

  async register(username: string, email: string, password: string, userAgent?: string, ip?: string) {
    const normalizedEmail = email.trim().toLowerCase();

    const existed = await this.userModel.findOne({ email: normalizedEmail }).exec();
    if (existed) {
      throw new BadRequestException({
        success: false,
        code: 'AUTH_EMAIL_EXISTS',
        message: '邮箱已被注册',
      });
    }

    const created = await this.userModel.create({
      username: username.trim(),
      email: normalizedEmail,
      passwordHash: this.hashPassword(password),
    });

    const tokens = await this.issueTokenBundle(created, userAgent, ip);
    return {
      user: this.sanitizeUser(created),
      ...tokens,
    };
  }

  async login(email: string, password: string, userAgent?: string, ip?: string) {
    const normalizedEmail = email.trim().toLowerCase();
    const user = await this.userModel.findOne({ email: normalizedEmail }).exec();

    if (!user || !this.verifyPassword(password, user.passwordHash)) {
      throw new UnauthorizedException({
        success: false,
        code: 'AUTH_INVALID_CREDENTIALS',
        message: '账号或密码错误',
      });
    }

    const tokens = await this.issueTokenBundle(user, userAgent, ip);
    return {
      user: this.sanitizeUser(user),
      ...tokens,
    };
  }

  async logout(refreshToken?: string) {
    if (refreshToken) {
      const hash = this.hashRefreshToken(refreshToken);
      await this.refreshTokenModel.updateMany(
        { refreshTokenHash: hash, revokedAt: null },
        { revokedAt: new Date() },
      );
    }

    return { success: true };
  }

  async me(accessToken?: string) {
    if (!accessToken) {
      throw new UnauthorizedException({
        success: false,
        code: 'AUTH_UNAUTHORIZED',
        message: '未登录',
      });
    }

    const payload = this.verifyAccessToken(accessToken);
    const user = await this.userModel.findById(new Types.ObjectId(payload.sub)).exec();

    if (!user) {
      throw new UnauthorizedException({
        success: false,
        code: 'AUTH_UNAUTHORIZED',
        message: '未登录',
      });
    }

    return this.sanitizeUser(user);
  }

  async refresh(refreshToken?: string, userAgent?: string, ip?: string) {
    if (!refreshToken) {
      throw new UnauthorizedException({
        success: false,
        code: 'AUTH_UNAUTHORIZED',
        message: '未登录',
      });
    }

    const hash = this.hashRefreshToken(refreshToken);
    const tokenDoc = await this.refreshTokenModel.findOne({
      refreshTokenHash: hash,
      revokedAt: null,
    }).exec();

    if (!tokenDoc || tokenDoc.expiresAt.getTime() < Date.now()) {
      throw new UnauthorizedException({
        success: false,
        code: 'AUTH_UNAUTHORIZED',
        message: '登录已过期，请重新登录',
      });
    }

    tokenDoc.revokedAt = new Date();
    await tokenDoc.save();

    const user = await this.userModel.findById(tokenDoc.userId).exec();
    if (!user) {
      throw new UnauthorizedException({
        success: false,
        code: 'AUTH_UNAUTHORIZED',
        message: '未登录',
      });
    }

    const tokens = await this.issueTokenBundle(user, userAgent, ip);
    return {
      user: this.sanitizeUser(user),
      ...tokens,
    };
  }
}
