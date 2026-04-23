import { Body, Controller, Get, Post, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { AuthService } from './auth.service';

@Controller('api/auth')
export class AuthController {
  private readonly accessTokenCookie = 'access_token';
  private readonly refreshTokenCookie = 'refresh_token';

  constructor(private readonly authService: AuthService) {}

  private getCookie(req: Request, key: string): string | undefined {
    const cookieHeader = req.headers?.cookie;
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

  private setAuthCookies(res: Response, accessToken: string, refreshToken: string) {
    const isProd = process.env.NODE_ENV === 'production';

    res.cookie(this.accessTokenCookie, accessToken, {
      httpOnly: true,
      sameSite: 'lax',
      secure: isProd,
      maxAge: 30 * 60 * 1000,
      path: '/',
    });

    res.cookie(this.refreshTokenCookie, refreshToken, {
      httpOnly: true,
      sameSite: 'lax',
      secure: isProd,
      maxAge: 15 * 24 * 60 * 60 * 1000,
      path: '/',
    });
  }

  private clearAuthCookies(res: Response) {
    const isProd = process.env.NODE_ENV === 'production';

    res.clearCookie(this.accessTokenCookie, {
      httpOnly: true,
      sameSite: 'lax',
      secure: isProd,
      path: '/',
    });

    res.clearCookie(this.refreshTokenCookie, {
      httpOnly: true,
      sameSite: 'lax',
      secure: isProd,
      path: '/',
    });
  }

  @Post('register')
  async register(
    @Body() body: { username: string; email: string; password: string },
    @Req() req: Request,
    @Res({ passthrough: true }) res: Response,
  ) {
    const result = await this.authService.register(
      body.username,
      body.email,
      body.password,
      req.headers['user-agent'],
      req.ip,
    );

    this.setAuthCookies(res, result.accessToken, result.refreshToken);

    return {
      success: true,
      message: '注册成功',
      data: {
        user: result.user,
        accessToken: result.accessToken,
      },
    };
  }

  @Post('login')
  async login(
    @Body() body: { email: string; password: string },
    @Req() req: Request,
    @Res({ passthrough: true }) res: Response,
  ) {
    const result = await this.authService.login(
      body.email,
      body.password,
      req.headers['user-agent'],
      req.ip,
    );

    this.setAuthCookies(res, result.accessToken, result.refreshToken);

    return {
      success: true,
      message: '登录成功',
      data: {
        user: result.user,
        accessToken: result.accessToken,
      },
    };
  }

  @Post('logout')
  async logout(@Req() req: Request, @Res({ passthrough: true }) res: Response) {
    const refreshToken = this.getCookie(req, this.refreshTokenCookie);
    await this.authService.logout(refreshToken);
    this.clearAuthCookies(res);

    return {
      success: true,
      message: '退出成功',
      data: true,
    };
  }

  @Get('me')
  async me(@Req() req: Request) {
    const accessToken =
      this.getCookie(req, this.accessTokenCookie) ||
      (req.headers.authorization?.startsWith('Bearer ')
        ? req.headers.authorization.slice('Bearer '.length)
        : undefined);

    const user = await this.authService.me(accessToken);

    return {
      success: true,
      message: '获取成功',
      data: user,
    };
  }

  @Post('refresh')
  async refresh(
    @Req() req: Request,
    @Res({ passthrough: true }) res: Response,
  ) {
    const refreshToken = this.getCookie(req, this.refreshTokenCookie);
    const result = await this.authService.refresh(refreshToken, req.headers['user-agent'], req.ip);

    this.setAuthCookies(res, result.accessToken, result.refreshToken);

    return {
      success: true,
      message: '刷新成功',
      data: {
        user: result.user,
        accessToken: result.accessToken,
      },
    };
  }
}
