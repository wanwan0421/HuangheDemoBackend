import { Injectable } from '@nestjs/common';
import { GoogleGenAI, Type } from '@google/genai';
import { LlmRecommendationResponse } from './interfaces/llmRecommendationResponse.interface';
import { InputNode } from './interfaces/modelResponse.interface';
import { indexRecommendationTool, modelRecommendationTool } from './schemas/llmTools.schema';
import { GenAIService } from '../genai/genai.service';
import { IndexService } from 'src/index/index.service';
import { ResourceService } from 'src/resource/resource.service';
import { ModelResource } from 'src/resource/schemas/modelResource.schema';

@Injectable()
export class LlmAgentService {
    constructor(private readonly indexService: IndexService,
        private readonly genAIService: GenAIService,
        private readonly resourceService: ResourceService,
    ) {}

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
