import { Body, Controller, Delete, Get, HttpException, HttpStatus, Param, Post, Query, Req, Sse } from '@nestjs/common';
import type { Request } from 'express';
import { defer, from, mergeMap, Observable } from 'rxjs';
import { ChatService } from './chat.service';
import { AuthService } from '../auth/auth.service';

@Controller('api/chat')
export class ChatController {
  constructor(
    private readonly chatService: ChatService,
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

  private getAccessToken(req: Request): string | undefined {
    return (
      this.getCookie(req, 'access_token') ||
      (req.headers.authorization?.startsWith('Bearer ')
        ? req.headers.authorization.slice('Bearer '.length)
        : undefined)
    );
  }

  private async resolveCurrentUserId(req: Request): Promise<string> {
    const accessToken = this.getAccessToken(req);
    if (!accessToken) {
      throw new HttpException('未登录', HttpStatus.UNAUTHORIZED);
    }

    const user = await this.authService.me(accessToken);
    return user.id;
  }

  // 会话管理
  @Post('sessions')
  async createSession(@Body('title') title?: string, @Req() req?: Request) {
    const userId = await this.resolveCurrentUserId(req as Request);
    const data = await this.chatService.createSession(title, userId);
    return { success: true, data };
  }

  @Get('sessions')
  async getSessions(@Query('limit') limit?: string, @Req() req?: Request) {
    const userId = await this.resolveCurrentUserId(req as Request);
    const parsed = limit ? parseInt(limit, 10) : 50;
    const data = await this.chatService.getSessions(userId, parsed);
    return { success: true, data };
  }

  @Get('sessions/:id')
  async getSession(@Param('id') id: string, @Req() req?: Request) {
    const userId = await this.resolveCurrentUserId(req as Request);
    const session = await this.chatService.getSession(id, userId);
    if (!session) {
      throw new HttpException('Session not found', HttpStatus.NOT_FOUND);
    }
    return { success: true, data: session };
  }

  @Post('sessions/:id')
  async updateSession(@Param('id') id: string, @Body() updates: any, @Req() req?: Request) {
    const userId = await this.resolveCurrentUserId(req as Request);
    const data = await this.chatService.updateSession(id, updates || {}, userId);
    return { success: true, data };
  }

  @Delete('sessions/:id')
  async deleteSession(@Param('id') id: string, @Req() req?: Request) {
    const userId = await this.resolveCurrentUserId(req as Request);
    await this.chatService.deleteSession(id, userId);
    return { success: true, message: 'Session deleted' };
  }

  @Get('sessions/:id/messages')
  async getMessages(@Param('id') id: string, @Query('limit') limit?: string, @Req() req?: Request) {
    const userId = await this.resolveCurrentUserId(req as Request);
    const parsed = limit ? parseInt(limit, 10) : 100;
    const data = await this.chatService.getMessages(id, userId, parsed);
    return { success: true, data };
  }

  @Delete('sessions/:id/messages')
  async clearMessages(@Param('id') id: string, @Req() req?: Request) {
    const userId = await this.resolveCurrentUserId(req as Request);
    await this.chatService.clearMessages(id, userId);
    return { success: true, message: 'Messages cleared' };
  }

  // 带记忆的 SSE
  @Sse('sessions/:sessionId/chat')
  chatWithSession(
    @Param('sessionId') sessionId: string,
    @Query('query') query: string,
    @Req() req?: Request,
  ): Observable<{ event?: string; data: any }> {
    if (!query) {
      throw new HttpException('Query is required', HttpStatus.BAD_REQUEST);
    }

    return defer(() =>
      from(this.resolveCurrentUserId(req as Request)).pipe(
        mergeMap((userId) => this.chatService.streamWithMemory(sessionId, query, userId)),
      ),
    );
  }

  @Post('sessions/:sessionId/align')
  async alignSession(@Param('sessionId') sessionId: string, @Req() req?: Request) {
    const userId = await this.resolveCurrentUserId(req as Request);
    const data = await this.chatService.alignSession(sessionId, userId);
    return { success: true, data };
  }
}
