import { Body, Controller, Delete, Get, HttpException, HttpStatus, Param, Post, Query, Sse } from '@nestjs/common';
import { Observable } from 'rxjs';
import { ChatService } from './chat.service';

@Controller('api/chat')
export class ChatController {
  constructor(private readonly chatService: ChatService) {}

  // 会话管理
  @Post('sessions')
  createSession(@Body('title') title?: string) {
    return this.chatService.createSession(title).then((data) => ({ success: true, data }));
  }

  @Get('sessions')
  getSessions(@Query('limit') limit?: string) {
    const parsed = limit ? parseInt(limit, 10) : 50;
    return this.chatService.getSessions(parsed).then((data) => ({ success: true, data }));
  }

  @Get('sessions/:id')
  async getSession(@Param('id') id: string) {
    const session = await this.chatService.getSession(id);
    if (!session) {
      throw new HttpException('Session not found', HttpStatus.NOT_FOUND);
    }
    return { success: true, data: session };
  }

  @Post('sessions/:id')
  updateSession(@Param('id') id: string, @Body('title') title: string) {
    return this.chatService.updateSession(id, { title }).then((data) => ({ success: true, data }));
  }

  @Delete('sessions/:id')
  async deleteSession(@Param('id') id: string) {
    await this.chatService.deleteSession(id);
    return { success: true, message: 'Session deleted' };
  }

  @Get('sessions/:id/messages')
  getMessages(@Param('id') id: string, @Query('limit') limit?: string) {
    const parsed = limit ? parseInt(limit, 10) : 100;
    return this.chatService.getMessages(id, parsed).then((data) => ({ success: true, data }));
  }

  @Delete('sessions/:id/messages')
  async clearMessages(@Param('id') id: string) {
    await this.chatService.clearMessages(id);
    return { success: true, message: 'Messages cleared' };
  }

  // 带记忆的 SSE
  @Sse('sessions/:id/chat')
  chatWithSession(
    @Param('id') sessionId: string,
    @Query('query') query: string,
  ): Observable<{ event?: string; data: any }> {
    if (!query) {
      throw new HttpException('Query is required', HttpStatus.BAD_REQUEST);
    }
    return this.chatService.streamWithMemory(sessionId, query);
  }
}
