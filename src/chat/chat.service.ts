import { Injectable, HttpException, HttpStatus } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { InjectModel } from '@nestjs/mongoose';
import { Model, Types } from 'mongoose';
import { Observable } from 'rxjs';
import { Session, SessionDocument } from './schemas/session.schema';
import { Message, MessageDocument } from './schemas/message.schema';
import { DataScanResult, DataScanResultDocument } from '../data-mapping/schemas/data-scan-result.schema';

@Injectable()
export class ChatService {
    constructor(
        private readonly httpService: HttpService,
        @InjectModel(Session.name) private readonly sessionModel: Model<SessionDocument>,
        @InjectModel(Message.name) private readonly messageModel: Model<MessageDocument>,
        @InjectModel(DataScanResult.name) private readonly dataScanResultModel: Model<DataScanResultDocument>,
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

    async alignSession(sessionId: string): Promise<any> {
        const session = await this.sessionModel.findById(sessionId).exec();
        if (!session) {
            throw new HttpException('Session not found', HttpStatus.NOT_FOUND);
        }

        if (!session.taskSpec || !session.modelContract) {
            throw new HttpException('Task spec or model contract is missing', HttpStatus.BAD_REQUEST);
        }

        // 从数据库中读取数据扫描结果
        const dataScanResults = await this.dataScanResultModel
            .find({ sessionId: sessionId, status: 'completed' })
            .sort({ createdAt: -1 })
            .exec();

        // 同一输入槽只保留最新一条（回退到文件路径），避免历史脏数据干扰对齐
        const latestBySlotOrPath = new Map<string, DataScanResultDocument>();
        for (const result of dataScanResults) {
            const key = (result as any).slotKey || result.filePath;
            if (!latestBySlotOrPath.has(key)) {
                latestBySlotOrPath.set(key, result);
            }
        }
        const latestResults = Array.from(latestBySlotOrPath.values()).reverse();

        // 组装文件类 data_profiles
        const scannedProfiles = latestResults.map((result, index) => ({
            file_id: `node_${sessionId}_${(result as any).slotKey || index}`,
            file_path: result.filePath,
            slot_key: (result as any).slotKey || null,
            profile: result.profile || {},
            timestamp: new Date().toISOString(),
            status: 'active',
        }));

        // 组装前端输入框参数类 data_profiles（例如阈值、系数、开关等）
        const manualProfiles = this.buildManualParameterProfiles(session.context, sessionId);
        const dataProfiles = [...scannedProfiles, ...manualProfiles];

        try {
            const response = await this.httpService.axiosRef({
                url: `${process.env.agentUrl}/align-session`,
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                data: {
                    session_id: sessionId,
                    task_spec: session.taskSpec,
                    model_contract: session.modelContract,
                    data_profiles: dataProfiles,
                },
            });

            const result = response.data || {};
            await this.sessionModel.findByIdAndUpdate(sessionId, {
                alignmentResult: result.alignment_result || {},
                alignmentStatus: result.alignment_status,
                goNoGo: result.go_no_go,
                canRunNow: result.can_run_now,
                updatedAt: new Date(),
            }).exec();

            return result;
        } catch (error) {
            const detail = error?.response?.data?.detail || error?.message || 'Align session failed';
            const statusCode = error?.response?.status || HttpStatus.BAD_GATEWAY;
            throw new HttpException(detail, statusCode);
        }
    }

    private buildManualParameterProfiles(context: any, sessionId: string): any[] {
        if (!context || typeof context !== 'object') {
            return [];
        }

        const candidates =
            context.manualInputs ||
            context.manual_inputs ||
            context.inputParams ||
            context.inputs ||
            [];

        const normalized = this.normalizeManualInputs(candidates);

        return normalized.map((item, index) => ({
            file_id: `manual_${sessionId}_${index}`,
            file_path: `manual://input/${item.name}`,
            profile: {
                Form: 'Parameter',
                Value_type: item.valueType,
                Unit: item.unit || 'Unknown',
                Parameter: {
                    name: item.name,
                    value: item.value,
                },
                Semantic: {
                    Abstract: `用户输入参数 ${item.name}`,
                    Applications: ['模型运行输入'],
                    Tags: ['manual', 'parameter'],
                },
            },
            timestamp: new Date().toISOString(),
            status: 'active',
        }));
    }

    private normalizeManualInputs(source: any): Array<{ name: string; value: any; unit?: string; valueType: string }> {
        if (Array.isArray(source)) {
            return source
                .map((item, idx) => {
                    const name = item?.name || item?.key || `manual_input_${idx + 1}`;
                    const value = item?.value;
                    const unit = item?.unit;
                    return {
                        name,
                        value,
                        unit,
                        valueType: this.inferValueType(value),
                    };
                })
                .filter((item) => item.value !== undefined && item.value !== null);
        }

        if (source && typeof source === 'object') {
            return Object.entries(source).map(([name, value]) => ({
                name,
                value,
                valueType: this.inferValueType(value),
            }));
        }

        return [];
    }

    private inferValueType(value: any): 'int' | 'float' | 'string' | 'boolean' {
        if (typeof value === 'boolean') {
            return 'boolean';
        }
        if (typeof value === 'number') {
            return Number.isInteger(value) ? 'int' : 'float';
        }
        if (typeof value === 'string') {
            const trimmed = value.trim();
            if (/^(true|false)$/i.test(trimmed)) {
                return 'boolean';
            }
            if (/^-?\d+$/.test(trimmed)) {
                return 'int';
            }
            if (/^-?\d+\.\d+$/.test(trimmed)) {
                return 'float';
            }
        }
        return 'string';
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
