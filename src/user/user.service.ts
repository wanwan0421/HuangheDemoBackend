import { Injectable, NotFoundException, UnauthorizedException } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import { randomUUID } from 'crypto';
import type { Request } from 'express';
import { User, UserDocument } from '../auth/schemas/user.schema';
import { AuthService } from '../auth/auth.service';

@Injectable()
export class UserService {
  constructor(
    @InjectModel(User.name)
    private readonly userModel: Model<UserDocument>,
    private readonly authService: AuthService,
  ) {}

  private getCookie(req: Request | undefined, key: string): string | undefined {
    const cookieHeader = req?.headers?.cookie;
    if (!cookieHeader) {
      return undefined;
    }

    const parts = cookieHeader.split(';');
    for (const part of parts) {
      const [rawKey, ...rest] = part.trim().split('=');
      if (rawKey === key) {
        return decodeURIComponent(rest.join('='));
      }
    }

    return undefined;
  }

  private getAccessToken(req?: Request): string | undefined {
    return (
      this.getCookie(req, 'access_token') ||
      (req?.headers.authorization?.startsWith('Bearer ')
        ? req.headers.authorization.slice('Bearer '.length)
        : undefined)
    );
  }

  private async resolveUserId(userId?: string, req?: Request): Promise<string> {
    const trimmedUserId = (userId || '').trim();
    if (trimmedUserId) {
      return trimmedUserId;
    }

    const accessToken = this.getAccessToken(req);
    if (!accessToken) {
      throw new UnauthorizedException('未登录');
    }

    const user = await this.authService.me(accessToken);
    return user.id;
  }

  private async getUser(userId?: string, req?: Request): Promise<UserDocument> {
    const resolvedUserId = await this.resolveUserId(userId, req);
    const user = await this.userModel.findById(resolvedUserId).exec();

    if (!user) {
      throw new NotFoundException('用户不存在');
    }

    const normalizedUser = user as any;
    let dirty = false;
    if (!Array.isArray(normalizedUser.favoriteModels)) {
      normalizedUser.favoriteModels = [];
      dirty = true;
    }
    if (!Array.isArray(normalizedUser.favoriteData)) {
      normalizedUser.favoriteData = [];
      dirty = true;
    }
    if (!Array.isArray(normalizedUser.simulationResults)) {
      normalizedUser.simulationResults = [];
      dirty = true;
    }

    if (dirty) {
      await user.save();
    }

    return user;
  }

  private getName(payload: any, fallback = 'unnamed'): string {
    if (typeof payload === 'string') {
      return payload;
    }

    if (payload && typeof payload === 'object') {
      const candidate =
        payload.name ?? payload.modelName ?? payload.title ?? payload.id ?? fallback;
      return String(candidate);
    }

    return fallback;
  }

  private normalizeObject(payload: any, fallbackName = 'unnamed'): Record<string, any> {
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
      return payload;
    }

    return {
      name: this.getName(payload, fallbackName),
      value: payload,
    };
  }

  async getFavoriteModels(userId?: string, req?: Request) {
    const doc = await this.getUser(userId, req);
    return (doc as any).favoriteModels || [];
  }

  async addFavoriteModel(payload: any, userId?: string, req?: Request) {
    const doc = await this.getUser(userId, req);
    const next = this.normalizeObject(payload, 'model');
    const name = this.getName(next, 'model');

    const current = ((doc as any).favoriteModels || []) as Record<string, any>[];
    const exists = current.some((item) => this.getName(item) === name);
    if (!exists) {
      current.push({ ...next, name, createdAt: new Date().toISOString() });
      (doc as any).favoriteModels = current;
      await doc.save();
    }

    return (doc as any).favoriteModels || [];
  }

  async removeFavoriteModel(name: string, userId?: string, req?: Request) {
    const doc = await this.getUser(userId, req);
    const target = decodeURIComponent(name);
    (doc as any).favoriteModels = ((doc as any).favoriteModels || []).filter(
      (item) => this.getName(item) !== target,
    );
    await doc.save();
    return (doc as any).favoriteModels || [];
  }

  async getFavoriteData(userId?: string, req?: Request) {
    const doc = await this.getUser(userId, req);
    return (doc as any).favoriteData || [];
  }

  async addFavoriteData(payload: any, userId?: string, req?: Request) {
    const doc = await this.getUser(userId, req);
    const next = this.normalizeObject(payload, 'data');
    const name = this.getName(next, 'data');

    const current = ((doc as any).favoriteData || []) as Record<string, any>[];
    const exists = current.some((item) => this.getName(item) === name);
    if (!exists) {
      current.push({ ...next, name, createdAt: new Date().toISOString() });
      (doc as any).favoriteData = current;
      await doc.save();
    }

    return (doc as any).favoriteData || [];
  }

  async removeFavoriteData(name: string, userId?: string, req?: Request) {
    const doc = await this.getUser(userId, req);
    const target = decodeURIComponent(name);
    (doc as any).favoriteData = ((doc as any).favoriteData || []).filter(
      (item) => this.getName(item) !== target,
    );
    await doc.save();
    return (doc as any).favoriteData || [];
  }

  async getSimulationResults(userId?: string, req?: Request) {
    const doc = await this.getUser(userId, req);
    return (doc as any).simulationResults || [];
  }

  async addSimulationResult(payload: any, userId?: string, req?: Request) {
    const doc = await this.getUser(userId, req);
    const next = this.normalizeObject(payload, 'simulation-result');

    const current = ((doc as any).simulationResults || []) as Record<string, any>[];
    current.push({
      ...next,
      id: next.id || randomUUID(),
      createdAt: next.createdAt || new Date().toISOString(),
    });
    (doc as any).simulationResults = current;

    await doc.save();
    return (doc as any).simulationResults || [];
  }
}
