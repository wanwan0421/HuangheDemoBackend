import { Injectable, HttpException, HttpStatus } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { InjectModel } from '@nestjs/mongoose';
import { Model, Types } from 'mongoose';
import { Observable, from } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { Session, SessionDocument } from './schemas/session.schema';
import { Message, MessageDocument } from './schemas/message.schema';

@Injectable()
export class ChatService {
    constructor(
        private readonly httpService: HttpService,
        @InjectModel(Session.name) private readonly sessionModel: Model<SessionDocument>,
        @InjectModel(Message.name) private readonly messageModel: Model<MessageDocument>,
    ) { }

    // ============ SSE 代理到 Python ============
    getSystemStream(query: string): Observable<{ event?: string; data: any }> {
        return new Observable((observer) => {
            this.httpService
                .axiosRef({
                    url: `${process.env.agentUrl}/stream?query=${encodeURIComponent(query)}`,
                    method: 'GET',
                    responseType: 'stream',
                })
                .then((response) => {
                    let buffer = '';
                    const heartbeat = setInterval(() => {
                        observer.next({ data: { type: 'heartbeat', message: 'keep-alive' } });
                    }, 20000);

                    response.data.on('data', (chunk: Buffer) => {
                        buffer += chunk.toString();
                        while (true) {
                            const nn = buffer.indexOf('\n\n');
                            const rrnn = buffer.indexOf('\r\n\r\n');
                            const sepIndex = nn === -1 ? rrnn : rrnn === -1 ? nn : Math.min(nn, rrnn);
                            if (sepIndex < 0) break;

                            const block = buffer.slice(0, sepIndex);
                            const sepLen = buffer.startsWith('\r\n', sepIndex) ? 4 : 2;
                            buffer = buffer.slice(sepIndex + sepLen);

                            let eventName: string | undefined;
                            const dataLines: string[] = [];

                            block.split(/\r?\n/).forEach((rawLine) => {
                                const line = rawLine.trim();
                                if (!line) return;
                                if (line.startsWith('event:')) {
                                    eventName = line.replace(/^event:\s*/, '');
                                } else if (line.startsWith('data:')) {
                                    dataLines.push(line.replace(/^data:\s*/, ''));
                                }
                            });

                            if (dataLines.length) {
                                const jsonStr = dataLines.join('\n');
                                try {
                                    const data = JSON.parse(jsonStr);
                                    observer.next(eventName ? { event: eventName, data } : { data });
                                } catch (err) {
                                    console.warn('SSE JSON parse error:', err);
                                }
                            }
                        }
                    });

                    response.data.on('end', () => {
                        clearInterval(heartbeat);
                        observer.complete();
                    });

                    response.data.on('error', (err) => {
                        clearInterval(heartbeat);
                        observer.next({ data: { type: 'error', message: err.message } });
                    });
                })
                .catch((err) => {
                    observer.next({ data: { type: 'error', message: err.message } });
                    observer.complete();
                });
        });
    }

    // ============ 会话管理 ============
    async createSession(title?: string): Promise<Session> {
        const session = new this.sessionModel({ title: title || '新对话', messageCount: 0 });
        return session.save();
    }

    async getSessions(limit = 50): Promise<Session[]> {
        return this.sessionModel.find().sort({ updatedAt: -1 }).limit(limit).exec();
    }

    async getSession(sessionId: string): Promise<Session | null> {
        return this.sessionModel.findById(sessionId).exec();
    }

    async updateSession(sessionId: string, updates: Partial<Session>): Promise<Session | null> {
        return this.sessionModel
            .findByIdAndUpdate(sessionId, { ...updates, updatedAt: new Date() }, { new: true })
            .exec();
    }

    async deleteSession(sessionId: string): Promise<void> {
        await this.messageModel.deleteMany({ sessionId: new Types.ObjectId(sessionId) }).exec();
        await this.sessionModel.findByIdAndDelete(sessionId).exec();
    }

    async saveMessage(
        sessionId: string,
        role: 'user' | 'assistant' | 'system',
        content: string,
        tools?: any,
    ): Promise<Message> {
        const message = new this.messageModel({
            sessionId: new Types.ObjectId(sessionId),
            role,
            content,
            tools,
        });

        const saved = await message.save();
        await this.sessionModel
            .findByIdAndUpdate(sessionId, {
                $inc: { messageCount: 1 },
                lastMessage: content.substring(0, 100),
                updatedAt: new Date(),
            })
            .exec();

        return saved;
    }

    async getMessages(sessionId: string, limit = 100): Promise<Message[]> {
        return this.messageModel
            .find({ sessionId: new Types.ObjectId(sessionId) })
            .sort({ timestamp: 1 })
            .limit(limit)
            .exec();
    }

    async getRecentMessages(sessionId: string, count = 10): Promise<Message[]> {
        const messages = await this.messageModel
            .find({ sessionId: new Types.ObjectId(sessionId) })
            .sort({ timestamp: -1 })
            .limit(count)
            .exec();

        return messages.reverse();
    }

    async clearMessages(sessionId: string): Promise<void> {
        await this.messageModel.deleteMany({ sessionId: new Types.ObjectId(sessionId) }).exec();
        await this.sessionModel
            .findByIdAndUpdate(sessionId, { messageCount: 0, lastMessage: null })
            .exec();
    }

    // ============ 上下文 + SSE ============
    streamWithMemory(sessionId: string, query: string): Observable<{ event?: string; data: any }> {
        if (!query) {
            throw new HttpException('Query is required', HttpStatus.BAD_REQUEST);
        }

        return from(this.saveUserMessageAndGetHistory(sessionId, query)).pipe(
            switchMap(({ history }): Observable<{ event?: string; data: any }> => {
                const contextQuery = this.buildContextQuery(history, query);

                return new Observable<{ event?: string; data: any }>((observer) => {
                    let aiResponse = '';
                    const tools: any[] = [];

                    this.getSystemStream(contextQuery).subscribe({
                        next: (event) => {
                            observer.next(event);
                            if (event.data?.type === 'token') {
                                aiResponse += event.data.message || '';
                            }
                            if (event.data?.tool) {
                                tools.push(event.data);
                            }
                        },
                        complete: async () => {
                            if (aiResponse) {
                                await this.saveMessage(sessionId, 'assistant', aiResponse, tools.length ? tools : undefined);
                            }
                            observer.complete();
                        },
                        error: (err) => observer.error(err),
                    });
                });
            }),
        );
    }

    private async saveUserMessageAndGetHistory(sessionId: string, query: string) {
        await this.saveMessage(sessionId, 'user', query);
        const history = await this.getRecentMessages(sessionId, 11);
        return { history: history.slice(0, -1) };
    }

    private buildContextQuery(history: Message[], currentQuery: string): string {
        if (!history.length) {
            return currentQuery;
        }

        const contextLines = history.map((msg) => {
            const role = msg.role === 'user' ? '用户' : 'AI';
            return `${role}: ${msg.content}`;
        });

        return `以下是之前的对话历史：
            ${contextLines.join('\n')}

            当前用户问题：${currentQuery}

            请根据上述对话历史和当前问题，给出恰当的回复。`;
                }
}
