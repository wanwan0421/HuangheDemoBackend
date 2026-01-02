import { Injectable } from '@nestjs/common';
import { LlmRecommendationResponse } from './interfaces/llmRecommendationResponse.interface';
import { InputNode } from './interfaces/modelResponse.interface';
import { indexRecommendationTool, modelRecommendationTool } from './schemas/llmTools.schema';
import { GenAIService } from '../genai/genai.service';
import { IndexService } from 'src/index/index.service';
import { ResourceService } from 'src/resource/resource.service';
import { ModelResource } from 'src/resource/schemas/modelResource.schema';
import { Observable } from 'rxjs';
import { HttpService } from '@nestjs/axios';
import { Response } from 'express';
import axios from 'axios';

@Injectable()
export class LlmAgentService {
    constructor(
        private readonly indexService: IndexService,
        private readonly genAIService: GenAIService,
        private readonly resourceService: ResourceService,
        private readonly httpsService: HttpService,
    ) {}

    /**
     * 调用Agent 负责与Python后端进行通信
     * @param prompt 用户输入
     * @returns 
     */
    getSystemErrorName(query: string): Observable<{ event?: string; data: any}> {
        // 每一次observer.next()就推送一个SSE事件
        return new Observable((observer) => {
            // 调用Python FastAPI后端接口
            this.httpsService.axiosRef({
                url: `${process.env.agentUrl}/stream?query=${encodeURIComponent(query)}`,
                method: 'GET',
                responseType: 'stream',
            }).then((response) => {
                let buffer = '';

                // 心跳保活，每20s发一次
                const heartbeat = setInterval(() => {
                    observer.next({ data: { type: "heartbeat", message: "keep-alive"} });
                }, 20000);

                // 处理SSE chunk（保留 event 行，避免被丢弃 token 等命名事件）
                response.data.on('data', (chunk: Buffer) => {
                    buffer += chunk.toString();
                    let sepIndex = -1;

                    // 兼容 \n\n 与 \r\n\r\n
                    while (true) {
                        const nn = buffer.indexOf('\n\n');
                        const rrnn = buffer.indexOf('\r\n\r\n');
                        if (nn === -1 && rrnn === -1) {
                            sepIndex = -1;
                        } else if (nn === -1) {
                            sepIndex = rrnn;
                        } else if (rrnn === -1) {
                            sepIndex = nn;
                        } else {
                            sepIndex = Math.min(nn, rrnn);
                        }

                        if (sepIndex < 0) break;

                        const block = buffer.slice(0, sepIndex);
                        // 跳过分隔符长度
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
                    observer.next({ data: { type: "error", message: err.message} });
                });
            }).catch((err) => {
                observer.next({ data: { type: "error", message: err.message} });
                observer.complete();
            });
        });
    }

    async pipePythonSSE(query: string, res: any) {
        const pythonUrl = `${process.env.agentUrl}/stream?query=${encodeURIComponent(query)}`;

        const pythonRes = await axios({
            method: 'GET',
            url: pythonUrl,
            responseType: 'stream',
            headers: {
                Accept: 'text/event-stream',
            },
        });

        // 管道传输数据到客户端
        pythonRes.data.on('data', (chunk: Buffer) => {
            res.write(chunk);
        });

        pythonRes.data.on('end', () => {
            res.end();
        });

        pythonRes.data.on('error', (err: any) => {
            res.write(
                `event: error\ndata: ${JSON.stringify({
                    type: 'error',
                    message: err.message,
                })}\n\n`,
            );
            res.end();
        });

        // 浏览器断开时，关闭 Python 流
        res.on('close', () => {
            pythonRes.data.destroy();
        });
    }

    /**
     * 调用LLM API，使用结构化输出获取5个指标推荐
     * @param prompt 用户输入
     * @param userQueryVector 用户输入转换为的向量
     * @returns 推荐的5个指标信息
     */
    private async reconmmendIndex(prompt: string, userQueryVector: number[]): Promise<LlmRecommendationResponse | null> {
        // 进行向量搜索，获取相近的10个指标信息
        const relevantIndex = await this.indexService.findRelevantIndex(userQueryVector);
        console.log("获取相近的10个指标信息:", relevantIndex);

        console.log("test stringify one");
        JSON.stringify(relevantIndex[0]);
        console.log("stringify one done");

        const contents = [
            {
                role: 'user',
                parts: [{
                    text: `
                        You are a professional expert in recommendation of geographical index.

                        IMPORTANT RULES (MUST FOLLOW):
                            1. You can ONLY choose index names that appear exactly in the Candidate Index Library.
                            2. The "name" field in your response must be name_en from the candidates.
                            3. Don't translate, summarize, rename, or invent new index names.
                            4. If no suitable index exists, do not use the tool.
                            5. If and only if you can confidently select 5 different index names, use the "recommend_index" tool. Otherwise, do not use any tool.

                        Candidate Index Library:
                        ${JSON.stringify(relevantIndex)}`
                }]
            },
            {
                role: 'user',
                parts: [{ text: prompt }]
            }
        ];

        console.log("contents: ", contents);

        try {
            const response = await this.genAIService.generateContent(contents, indexRecommendationTool);
            console.log(response);

            // 检查LLM是否决定使用工具，即推荐了模型
            if (response.functionCalls && response.functionCalls.length > 0) {
                const functionCall = response.functionCalls?.[0];

                if (functionCall.name === 'recommend_index') {
                    const functionCallArgs = functionCall.args as any;

                    const recommendations = functionCallArgs?.['recommendations'];

                    if (Array.isArray(recommendations) && recommendations.length > 0) {
                        return {
                            recommendations: recommendations.map(item => ({
                                name: item.name,
                                reason: item.reason
                            }))
                        }
                    }
                }
            }
            return null;
        } catch (error) {
            console.log("推荐指标信息错误：", error);
            return null;
        }
    }

    /**
     * 调用LLM API，使用结构化输出获取最终推荐的模型
     * @param prompt 用户输入
     * @returns 推荐的模型信息
     */
    public async reconmmendModel(prompt: string) {
        // 将用户的提问转化为向量
        const userQueryVector = await this.genAIService.generateEmbedding(prompt);

        // 指标推荐
        const indexRecommendation = await this.reconmmendIndex(prompt, userQueryVector);

        // 如果没有推荐结果，直接返回
        if (!indexRecommendation || !indexRecommendation.recommendations) {
            console.log("未获取到推荐指标信息！");
            return null;
        }
        console.log("指标信息:", JSON.stringify(indexRecommendation.recommendations));

        // 获取指标名称并反查指标详细信息
        const indexNames = indexRecommendation.recommendations.map(r => r.name);
        const index = await this.indexService.getIndicatorByNames(indexNames);
        const modelIdSet = new Set<string>();

        index.forEach(index => {
            index.models?.forEach(model => {
                if (model.model_id) {
                    modelIdSet.add(model.model_id);
                }
            })
        });

        const modelIds = Array.from(modelIdSet);
        if (!modelIds.length) {
            return null;
        }

        // 进行向量搜索，获取相近的5个模型的名称
        const relevantModel = await this.indexService.findRelevantModel(userQueryVector, modelIds);

        // 获取5个模型的详细信息
        const fetchModelDetails = relevantModel.map(index => this.resourceService.getModelDetails(index.modelMd5));
        const modelDetailsResults = await Promise.all(fetchModelDetails);

        // 精简模型信息
        const simpleModelList = modelDetailsResults
            .filter((item): item is ModelResource => item != null && item !== undefined)
            .map(model => {
                return {
                    name: model.name,
                    md5: model.md5,
                    description: model.description,
                    mdl: model.mdl
                }
            });

        const contents = [
            {
                role: 'user',
                parts: [{
                    text:
                    `You are a professional expert in recommendation of geographical model. 

                    IMPORTANT RULES (MUST FOLLOW):
                            1. You can only choose model md5 that appear exactly in the Candidate Model Library.
                            2. The "md5" field in your response must be md5 from the candidates.
                            3. Don't translate, summarize, rename, or invent new model md5.
                            4. If no suitable model exists, do not use the tool.
                            5. You need to compare their descriptions and mdl and use the "recommend_model" tool to select the most relevant model.

                        Candidate Models Library:
                        ${JSON.stringify(simpleModelList)}

                        If the request is unrelated to geographic models, do not use the tool.`
                }]
            },
            {
                role: 'user',
                parts: [{ text: prompt }]
            }
        ];

        try {
            const response = await this.genAIService.generateContent(contents, modelRecommendationTool);
            console.log("推荐模型返回结果：", response.functionCalls?.[0]);

            // 检查LLM是否决定使用工具，即推荐了模型
            if (response.functionCalls && response.functionCalls.length > 0) {
                const functionCall = response.functionCalls?.[0];

                if (functionCall.name === 'recommend_model') {
                    const functionCallArgs = functionCall.args as any;

                    const recommendModelMd5 = functionCallArgs?.['md5'];
                    const recommendModelReason = functionCallArgs?.['reason'];

                    // 再从数据库获取最终模型的完整详情
                    const finalModel = await this.resourceService.getModelDetails(recommendModelMd5);

                    if (finalModel && finalModel.data?.input) {
                        const workflowSteps = finalModel.data.input.map((state, stateIndex) => {
                            return {
                                stateName: state.stateName,
                                stateDescription: state.stateDescription,
                                events: state.events.map((event, eventIndex) => {
                                    const eventData = event.eventData;
                                    const inputs: InputNode[] = [];

                                    // 解析internal节点
                                    if (eventData.eventDataType == 'internal' && eventData.nodeList) {
                                        eventData.nodeList.forEach(node => {
                                            inputs.push({
                                                name: node.name,
                                                key: `${state.stateName}_${event.eventName}_${node.name}`,
                                                type: node.dataType,
                                                description: node.description
                                            })
                                        })
                                    }

                                    // 解析external节点
                                    if (eventData.eventDataType == 'external') {
                                        inputs.push({
                                            name: eventData.eventDataName || event.eventName,
                                            key: `${state.stateName}_${event.eventName}_${eventData.eventDataName}`,
                                            type: 'FILE',
                                            description: eventData.exentDataDesc
                                        })
                                    }
                                    return {
                                        eventName: event.eventName,
                                        eventDescription: event.eventDescription,
                                        inputs: inputs
                                    }
                                })
                            };
                        });

                        return {
                            name: finalModel.name,
                            description: finalModel.description,
                            reason: recommendModelReason,
                            workflow: workflowSteps
                        }
                    };
                }
            }
            return null;
        } catch (error) {
            console.log("推荐模型信息错误：", error);
            return null;
        }
    }

}
