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
     * 调用LLM API，使用结构化输出获取五个指标推荐
     * @param prompt 用户输入
     * @returns 推荐的5个模型信息
     */
    private async reconmmendIndex(prompt: string): Promise<LlmRecommendationResponse | null> {
        // 将用户的提问转化为向量
        const userQueryVector = await this.genAIService.generateEmbedding(prompt);

        // 进行向量搜索，获取相近的20个指标信息
        const relevantIndex = await this.indexService.findRelevantIndex(userQueryVector);

        const contents = [
            {
                role: 'system',
                content: `You are a professional geographic computing model agent.
                            Your task is:
                            1. Analyze the user's needs.
                            2. From the 20 candidate models provided below, select the 5 appropriate ones.
                            3. Use the 'recommend_index' tool to return these 5 recommendations.
                            
                            Candidate Models Library:
                            ${JSON.stringify(relevantIndex)}
                            
                            If the request is unrelated to geographic models, do not use the tool.`
            },
            {
                role: 'user',
                content: prompt,
            }
        ];

        try {
            const response = await this.genAIService.generateContent({
                model: 'gemini-2.5-flash',
                contents: contents,
                config: {
                    tools: [{
                        functionDeclarations: [indexRecommendationTool]
                    }],
                },
            });

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
            return null;
        }
    }

    /**
     * 调用LLM API，使用结构化输出获取最终推荐的模型
     * @param prompt 用户输入
     * @returns 推荐的模型信息
     */
    public async reconmmendModel(prompt: string) {
        const indexRecommendation = await this.reconmmendIndex(prompt);

        // 如果没有推荐结果，直接返回
        if (!indexRecommendation || !indexRecommendation.recommendations) {
            return null;
        }

        const fetchModelDetails = indexRecommendation.recommendations.map(index => this.resourceService.getModelDetails(index.name))
        // 等待所有查询完成
        const modelDetailsResults = await Promise.all(fetchModelDetails);

        // 精简模型信息
        const simpleModelList = modelDetailsResults
            .filter((item): item is ModelResource => item != null && item !== undefined)
            .map(model => {
                return {
                    name: model.name,
                    description: model.description,
                    mdl: model.mdl
                }
            });

        const contents = [
            {
                role: 'system',
                content: `You are a senior geographic information scientist. 
                          Below are the 5 candidate models with their full technical details:
                          ${JSON.stringify(simpleModelList)}
                          
                          Compare their descriptions and MDL (Model Description Language) logic carefully.
                          Select the ONE best model that perfectly fits the user's request.
                          Provide a technical reason for your choice.`
            },
            {
                role: 'user',
                content: prompt
            }
        ];

        try {
            const response = await this.genAIService.generateContent({
                model: 'gemini-2.5-flash',
                contents: contents,
                config: {
                    tools: [{
                        functionDeclarations: [modelRecommendationTool]
                    }],
                },
            });

            // 检查LLM是否决定使用工具，即推荐了模型
            if (response.functionCalls && response.functionCalls.length > 0) {
                const functionCall = response.functionCalls?.[0];

                if (functionCall.name === 'recommend_model') {
                    const functionCallArgs = functionCall.args as any;

                    const recommendModelName = functionCallArgs?.['name'];
                    const recommendModelReason = functionCallArgs?.['reason'];

                    // 再从数据库获取最终模型的完整详情
                    const finalModel = await this.resourceService.getModelDetails(recommendModelName);

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
                            name: recommendModelName,
                            reason: recommendModelReason,
                            workflow: workflowSteps
                        }
                    };
                }
            }
            return null;
        } catch (error) {
            return null;
        }
    }
}
