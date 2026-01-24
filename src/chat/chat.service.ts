import { Injectable, HttpException, HttpStatus } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { InjectModel } from '@nestjs/mongoose';
import { model, Model, Types } from 'mongoose';
import { Observable } from 'rxjs';
import { Session, SessionDocument } from './schemas/session.schema';
import { Message, MessageDocument } from './schemas/message.schema';

@Injectable()
export class ChatService {
    constructor(
        private readonly httpService: HttpService,
        @InjectModel(Session.name) private readonly sessionModel: Model<SessionDocument>,
        @InjectModel(Message.name) private readonly messageModel: Model<MessageDocument>,
    ) { }

    // ============ SSE 代理到 Python（带 thread_id） ============
    getSystemStream(query: string, sessionId?: string): Observable<{ event?: string; data: any }> {
        return new Observable((observer) => {
            this.httpService
                .axiosRef({
                    url: `${process.env.agentUrl}/stream?query=${encodeURIComponent(query)}${sessionId ? `&sessionId=${encodeURIComponent(sessionId)}` : ''}`,
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
        role: 'user' | 'AI' | 'system',
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

    // ============ 流式对话，记忆交给 LangGraph checkpointer ============
    streamWithMemory(sessionId: string, query: string): Observable<{ event?: string; data: any }> {
        if (!query) {
            throw new HttpException('Query is required', HttpStatus.BAD_REQUEST);
        }

        return new Observable<{ event?: string; data: any }>((observer) => {
            let aiResponse = '';
            const tools: any[] = [];
            let finalModelData: any = null;
            let taskSpecData: any = null;
            let modelContractData: any = null;

            // 记录用户消息（可选，用于历史查看；对话记忆交由 LangGraph）
            void this.saveMessage(sessionId, 'user', query).catch(() => undefined);

            // 调用Python，传入sessionId作为thread_id
            // LangGraph会根据thread_id自动加载和保存对话记忆
            this.getSystemStream(query, sessionId).subscribe({
                next: (event) => {
                    observer.next(event);
                    const payload = event.data;
                    console.log('Received payload:', payload);
                    if (payload?.type === 'token') {
                        aiResponse += payload.message || '';
                    }
                    if (payload?.tool && payload.type === 'tool_result') {
                        tools.push(payload);
                    }
                    if (payload.type === 'tool_result' && payload.tool === 'get_model_details' && payload.data) {
                        finalModelData = payload.data;
                        this.sessionModel.findByIdAndUpdate(sessionId, {
                            recommendedModel: {
                                name: finalModelData.name,
                                md5: finalModelData.md5,
                                description: finalModelData.description,
                                workflow: finalModelData.workflow,
                            },
                            updatedAt: new Date(),
                        }).exec().then(() => console.log('Model details pre-saved.')).catch(err => console.error('Pre-save error:', err));
                    }
                    if (payload.type === 'task_spec_generated' && payload.data) {
                        taskSpecData = payload.data;
                        this.sessionModel.findByIdAndUpdate(sessionId, {
                            taskSpec: taskSpecData,
                            updatedAt: new Date(),
                        }).exec().then(() => console.log('Task spec pre-saved.')).catch(err => console.error('Pre-save error:', err));
                    }
                    if (payload.type === 'model_contract_generated' && payload.data) {
                        modelContractData = payload.data;
                        this.sessionModel.findByIdAndUpdate(sessionId, {
                            modelContract: modelContractData,
                            updatedAt: new Date(),
                        }).exec().then(() => console.log('Model contract pre-saved.')).catch(err => console.error('Pre-save error:', err));
                    }
                },
                complete: async () => {
                    await this.persistFinalData(sessionId, aiResponse, tools, finalModelData, taskSpecData, modelContractData);
                    observer.complete();
                },
                error: async (err) => {
                    console.error('SSE Stream Interrupted:', err.message);
                    // 即便断开了，也要把已经拿到的部分 AI 回答存入数据库
                    await this.persistFinalData(sessionId, aiResponse, tools, finalModelData, taskSpecData, modelContractData);
                    observer.error(err);
                },
            });
        });
    }

    // 提取公共保存逻辑
    private async persistFinalData(sessionId: string, aiResponse: string, tools: any[], modelData: any, taskSpecData: any, modelContractData: any) {
        try {
            const tasks: Promise<any>[] = [];
            if (aiResponse || tools.length > 0) {
                tasks.push(this.saveMessage(sessionId, 'AI', aiResponse, tools.length ? tools : undefined));
            }
            // 如果 next 中没存成功，这里作为兜底
            if (modelData) {
                tasks.push(this.sessionModel.findByIdAndUpdate(sessionId, {
                    recommendedModel: modelData,
                    updatedAt: new Date(),
                }).exec());
            }
            if (taskSpecData) {
                tasks.push(this.sessionModel.findByIdAndUpdate(sessionId, {
                    taskSpec: taskSpecData,
                    updatedAt: new Date(),
                }).exec());
            }
            if (modelContractData) {
                tasks.push(this.sessionModel.findByIdAndUpdate(sessionId, {
                    modelContract: modelContractData,
                    updatedAt: new Date(),
                }).exec());
            }
            await Promise.all(tasks);
        } catch (e) {
            console.error('Final persistence failed:', e);
        }
    }
}
