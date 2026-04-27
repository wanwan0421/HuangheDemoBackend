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

    private async getOwnedSession(sessionId: string, userId: string): Promise<SessionDocument> {
        const session = await this.sessionModel.findOne({ _id: sessionId, userId }).exec();
        if (!session) {
            throw new HttpException('Session not found', HttpStatus.NOT_FOUND);
        }
        return session;
    }

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
    async createSession(title: string | undefined, userId: string): Promise<Session> {
        const session = new this.sessionModel({ title: title || '新对话', userId, messageCount: 0 });
        return session.save();
    }

    async getSessions(userId: string, limit = 50): Promise<Session[]> {
        return this.sessionModel.find({ userId }).sort({ updatedAt: -1 }).limit(limit).exec();
    }

    async getSession(sessionId: string, userId: string): Promise<Session | null> {
        return this.sessionModel.findOne({ _id: sessionId, userId }).exec();
    }

    async updateSession(sessionId: string, updates: Partial<Session>, userId: string): Promise<Session | null> {
        return this.sessionModel
            .findOneAndUpdate({ _id: sessionId, userId }, { ...updates, updatedAt: new Date() }, { new: true })
            .exec();
    }

    async deleteSession(sessionId: string, userId: string): Promise<void> {
        await this.getOwnedSession(sessionId, userId);
        await this.messageModel.deleteMany({ sessionId: new Types.ObjectId(sessionId) }).exec();
        await this.sessionModel.findByIdAndDelete(sessionId).exec();
    }

    async saveMessage(
        sessionId: string,
        role: 'user' | 'AI',
        content: string,
        tools?: any,
    ): Promise<Message> {
        const normalizedTools = Array.isArray(tools)
            ? tools
            : tools
                ? [tools]
                : [];

        const message = new this.messageModel({
            sessionId: new Types.ObjectId(sessionId),
            role,
            content,
            type: normalizedTools.length > 0 ? 'tool' : 'text',
            tools: normalizedTools,
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

    async getMessages(sessionId: string, userId: string, limit = 100): Promise<Message[]> {
        await this.getOwnedSession(sessionId, userId);
        const messages = await this.messageModel
            .find({ sessionId: new Types.ObjectId(sessionId) })
            .sort({ timestamp: 1 })
            .limit(limit)
            .lean()
            .exec();

        return messages.map((message: any) => {
            let normalizedTools: any[] = [];

            if (Array.isArray(message.tools)) {
                normalizedTools = message.tools;
            } else if (message.tools && typeof message.tools === 'object') {
                normalizedTools = message.tools.tool ? [message.tools] : Object.values(message.tools);
            }

            const content = typeof message.content === 'string' ? message.content : '';

            return {
                ...message,
                content,
                tools: normalizedTools,
                type: normalizedTools.length > 0 ? 'tool' : (message.type || 'text'),
            };
        }) as any;
    }

    async getRecentMessages(sessionId: string, count = 10): Promise<Message[]> {
        const messages = await this.messageModel
            .find({ sessionId: new Types.ObjectId(sessionId) })
            .sort({ timestamp: -1 })
            .limit(count)
            .exec();

        return messages.reverse();
    }

    async clearMessages(sessionId: string, userId: string): Promise<void> {
        await this.getOwnedSession(sessionId, userId);
        await this.messageModel.deleteMany({ sessionId: new Types.ObjectId(sessionId) }).exec();
        await this.sessionModel
            .findByIdAndUpdate(sessionId, { messageCount: 0, lastMessage: null })
            .exec();
    }

    async alignSession(sessionId: string, userId: string): Promise<any> {
        const session = await this.getOwnedSession(sessionId, userId);

        if (!session.taskSpec || !session.modelContract) {
            throw new HttpException('Task spec or model contract is missing', HttpStatus.BAD_REQUEST);
        }

        // 优先使用 session 中已保存的扫描结果，避免重复查询；若不存在则回退到 dataScanResults 集合
        const scannedProfiles = await this.buildScannedProfiles(sessionId, session.profile);

        // 组装前端输入框参数类 data_profiles（例如阈值、系数、开关等）
        const manualProfiles = this.buildManualParameterProfiles(session.context, sessionId, session.modelContract);
        const dataProfiles = [...scannedProfiles, ...manualProfiles];

        try {
            const result = await this.readAlignStreamFinal({
                session_id: sessionId,
                task_spec: session.taskSpec,
                model_contract: session.modelContract,
                data_profiles: dataProfiles,
            });

            const alignmentResult = result.alignment_result || {};
            const normalizedGoNoGo = result.go_no_go ?? alignmentResult.go_no_go;
            const normalizedCanRunNow = result.can_run_now ?? alignmentResult.can_run_now;

            await this.sessionModel.findByIdAndUpdate(sessionId, {
                alignmentResult: alignmentResult,
                alignmentStatus: result.alignment_status,
                goNoGo: normalizedGoNoGo,
                canRunNow: normalizedCanRunNow,
                updatedAt: new Date(),
            }).exec();

            return {
                status: result.status || 'success',
                session_id: result.session_id || sessionId,
                alignment_status: result.alignment_status,
                alignment_result: alignmentResult,
            };
        } catch (error: any) {
            const detail = error?.response?.data?.detail || error?.message || 'Align session failed';
            const statusCode = error?.response?.status || HttpStatus.BAD_GATEWAY;
            throw new HttpException(detail, statusCode);
        }
    }

    private async readAlignStreamFinal(requestBody: Record<string, any>): Promise<any> {
        return new Promise((resolve, reject) => {
            this.httpService
                .axiosRef({
                    url: `${process.env.agentUrl}/align-session/stream`,
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Accept: 'text/event-stream',
                    },
                    responseType: 'stream',
                    data: requestBody,
                })
                .then((response) => {
                    let buffer = '';
                    let finalPayload: any = null;

                    response.data.on('data', (chunk: Buffer) => {
                        buffer += chunk.toString();

                        while (true) {
                            const nn = buffer.indexOf('\n\n');
                            const rrnn = buffer.indexOf('\r\n\r\n');
                            const sepIndex = nn === -1 ? rrnn : rrnn === -1 ? nn : Math.min(nn, rrnn);
                            if (sepIndex < 0) {
                                break;
                            }

                            const block = buffer.slice(0, sepIndex);
                            const sepLen = buffer.startsWith('\r\n', sepIndex) ? 4 : 2;
                            buffer = buffer.slice(sepIndex + sepLen);

                            const dataLines: string[] = [];
                            block.split(/\r?\n/).forEach((rawLine) => {
                                const line = rawLine.trim();
                                if (!line) {
                                    return;
                                }
                                if (line.startsWith('data:')) {
                                    dataLines.push(line.replace(/^data:\s*/, ''));
                                }
                            });

                            if (!dataLines.length) {
                                continue;
                            }

                            const jsonStr = dataLines.join('\n');
                            try {
                                const payload = JSON.parse(jsonStr);
                                if (payload?.type === 'error') {
                                    reject(new HttpException(payload?.message || 'Align session stream error', HttpStatus.BAD_GATEWAY));
                                    response.data.destroy();
                                    return;
                                }
                                if (payload?.type === 'final' && payload?.data) {
                                    finalPayload = payload.data;
                                }
                            } catch (err) {
                                console.warn('alignSession SSE JSON parse error:', err);
                            }
                        }
                    });

                    response.data.on('end', () => {
                        if (finalPayload) {
                            resolve(finalPayload);
                            return;
                        }
                        reject(new HttpException('Align session stream ended without final payload', HttpStatus.BAD_GATEWAY));
                    });

                    response.data.on('error', (err) => {
                        reject(new HttpException(err?.message || 'Align session stream failed', HttpStatus.BAD_GATEWAY));
                    });
                })
                .catch((err) => {
                    reject(err);
                });
        });
    }

    private async buildScannedProfiles(sessionId: string, sessionProfileStore: any): Promise<any[]> {
        const sessionProfiles = this.normalizeSessionProfileStore(sessionId, sessionProfileStore);
        if (sessionProfiles.length > 0) {
            return sessionProfiles;
        }

        const dataScanResults = await this.dataScanResultModel
            .find({ sessionId: sessionId, status: 'completed' })
            .sort({ createdAt: -1 })
            .exec();

        const latestBySlotOrPath = new Map<string, DataScanResultDocument>();
        for (const result of dataScanResults) {
            const key = (result as any).slotKey || result.filePath;
            if (!latestBySlotOrPath.has(key)) {
                latestBySlotOrPath.set(key, result);
            }
        }

        return Array.from(latestBySlotOrPath.values())
            .reverse()
            .map((result, index) => ({
                file_id: `node_${sessionId}_${(result as any).slotKey || index}`,
                file_path: result.filePath,
                slot_key: (result as any).slotKey || null,
                profile: result.profile || {},
                timestamp: new Date().toISOString(),
                status: 'active',
            }));
    }

    private normalizeSessionProfileStore(sessionId: string, sessionProfileStore: any): any[] {
        let entries: any[] = [];

        if (Array.isArray(sessionProfileStore)) {
            entries = sessionProfileStore;
        } else if (Array.isArray(sessionProfileStore?.data_profiles)) {
            entries = sessionProfileStore.data_profiles;
        } else if (sessionProfileStore && typeof sessionProfileStore === 'object') {
            entries = [sessionProfileStore];
        }

        return entries
            .map((entry, index) => this.toScannedProfileEntry(entry, sessionId, index))
            .filter(Boolean);
    }

    private toScannedProfileEntry(entry: any, sessionId: string, index: number): any | null {
        if (!entry || typeof entry !== 'object') {
            return null;
        }

        const slotKey = entry.slot_key || entry.slotKey || entry.profile?.slot_key || entry.profile?.slotKey || null;
        const profile = entry.profile && typeof entry.profile === 'object'
            ? entry.profile
            : entry;
        const filePath = this.resolveProfileFilePath(entry) || this.resolveProfileFilePath(profile) || `session://profile/${slotKey || index}`;

        return {
            file_id: entry.file_id || entry.fileId || `node_${sessionId}_${slotKey || index}`,
            file_path: filePath,
            slot_key: slotKey,
            profile,
            timestamp: entry.timestamp || new Date().toISOString(),
            status: entry.status || 'active',
        };
    }

    private resolveProfileFilePath(profileEntry: any): string | null {
        if (!profileEntry || typeof profileEntry !== 'object') {
            return null;
        }

        const directPath =
            profileEntry.file_path ||
            profileEntry.filePath ||
            profileEntry.primary_file ||
            profileEntry.primaryFile ||
            profileEntry.path;

        if (typeof directPath === 'string' && directPath.trim()) {
            return directPath;
        }

        const firstSource = Array.isArray(profileEntry.data_sources)
            ? profileEntry.data_sources.find((item: any) => typeof item?.file_path === 'string' && item.file_path.trim())
            : null;

        return firstSource?.file_path || null;
    }

    private buildManualParameterProfiles(context: any, sessionId: string, modelContract?: any): any[] {
        if (!context || typeof context !== 'object') {
            return [];
        }

        const candidates =
            context.manualInputs ||
            context.manual_inputs ||
            context.inputParams ||
            context.inputs ||
            context;

        const normalized = this.normalizeManualInputs(candidates, modelContract);

        return normalized.map((item, index) => ({
            file_id: `manual_${sessionId}_${index}`,
            file_path: `manual://input/${item.name}`,
            slot_key: item.name,
            profile: {
                Form: 'Parameter',
                Value_type: item.valueType,
                Unit: item.unit || 'Unknown',
                Parameter: {
                    name: item.name,
                    value: item.value,
                },
                Semantic: {
                    Abstract: item.semanticRequirement
                        ? `用户输入参数 ${item.name}。语义要求：${item.semanticRequirement}`
                        : `用户输入参数 ${item.name}`,
                    Applications: ['模型运行输入'],
                    Tags: ['manual', 'parameter'],
                },
            },
            timestamp: new Date().toISOString(),
            status: 'active',
        }));
    }

    private normalizeManualInputs(source: any, modelContract?: any): Array<{ name: string; value: any; unit?: string; valueType: string; semanticRequirement?: string }> {
        const parameterContractMap = new Map<string, any>();
        const requiredSlots = Array.isArray(modelContract?.Required_slots) ? modelContract.Required_slots : [];

        for (const slot of requiredSlots) {
            if (String(slot?.Data_type || '').toLowerCase() === 'parameter' && slot?.Input_name) {
                parameterContractMap.set(slot.Input_name, slot);
            }
        }

        if (Array.isArray(source)) {
            return source
                .map((item, idx) => {
                    const name = item?.name || item?.key || `manual_input_${idx + 1}`;
                    const value = item?.value;
                    const unit = item?.unit;
                    const slotMeta = parameterContractMap.get(name);
                    return {
                        name,
                        value,
                        unit,
                        valueType: this.inferValueType(value),
                        semanticRequirement: slotMeta?.Semantic_requirement,
                    };
                })
                .filter((item) => {
                    if (item.value === undefined || item.value === null) {
                        return false;
                    }
                    if (parameterContractMap.size === 0) {
                        return true;
                    }
                    return parameterContractMap.has(item.name);
                });
        }

        if (source && typeof source === 'object') {
            return Object.entries(source)
                .map(([name, rawValue]) => {
                    if (parameterContractMap.size > 0 && !parameterContractMap.has(name)) {
                        return null;
                    }

                    const slotMeta = parameterContractMap.get(name);
                    if (rawValue && typeof rawValue === 'object' && !Array.isArray(rawValue)) {
                        const rawValueObject = rawValue as Record<string, any>;
                        const value =
                            rawValueObject.value ??
                            rawValueObject.defaultValue ??
                            rawValueObject.currentValue ??
                            rawValueObject.inputValue;

                        if (value === undefined || value === null) {
                            return null;
                        }

                        return {
                            name: rawValueObject.name || rawValueObject.key || name,
                            value,
                            unit: rawValueObject.unit,
                            valueType: this.inferValueType(value),
                            semanticRequirement: slotMeta?.Semantic_requirement,
                        };
                    }

                    if (rawValue === undefined || rawValue === null || Array.isArray(rawValue)) {
                        return null;
                    }

                    return {
                        name,
                        value: rawValue,
                        valueType: this.inferValueType(rawValue),
                        semanticRequirement: slotMeta?.Semantic_requirement,
                    };
                })
                .filter(Boolean) as Array<{ name: string; value: any; unit?: string; valueType: string; semanticRequirement?: string }>;
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
    streamWithMemory(sessionId: string, query: string, userId: string): Observable<{ event?: string; data: any }> {
        if (!query) {
            throw new HttpException('Query is required', HttpStatus.BAD_REQUEST);
        }

        return new Observable<{ event?: string; data: any }>((observer) => {
            let aiResponse = '';
            const tools: any[] = [];
            let finalModelData: any = null;
            let taskSpecData: any = null;
            let modelContractData: any = null;

            this.getOwnedSession(sessionId, userId).then(() => {
                // 记录用户消息（可选，用于历史查看；对话记忆交由 LangGraph）
                void this.saveMessage(sessionId, 'user', query).catch(() => undefined);

                // 调用Python，传入sessionId作为thread_id
                // LangGraph会根据thread_id自动加载和保存对话记忆
                this.getSystemStream(query, sessionId).subscribe({
                    next: (event) => {
                        observer.next(event);
                        const payload = event.data;
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
                        // 即便断开了，也要把已经拿到的部分 AI 回答存入数据库
                        await this.persistFinalData(sessionId, aiResponse, tools, finalModelData, taskSpecData, modelContractData);
                        observer.error(err);
                    },
                });
            }).catch((err) => {
                observer.error(err);
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
