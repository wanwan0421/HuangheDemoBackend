import { Injectable } from '@nestjs/common';
import { GoogleGenAI, Type } from '@google/genai';
import { LlmRecommendationResponse } from './interfaces/llmRecommendationResponse.interface';
import { modelRecommendationTool } from './schemas/llmTools.schema';
import { IndexService } from 'src/index/index.service';
import { GenAIService } from './genai.service';

@Injectable()
export class LlmAgentService {
    constructor(private readonly indexService: IndexService,
        private readonly genAIService: GenAIService,
    ) {}

    /**
     * 调用LLM API，使用结构化输出获取五个指标推荐
     * @param prompt 用户输入
     * @returns 推荐的5个模型信息
     */
    private async callLLMForRecommendation(promt: string): Promise<LlmRecommendationResponse | null> {
        // 将用户的提问转化为向量
        const userQueryVector = await this.genAIService.generateEmbedding(promt);

        // 进行向量搜索，获取相近的20个指标信息
        const relevantIndex = await this.indexService.findRelevantIndex(userQueryVector);

        const contents = [
            {
                role: 'system',
                content: `You are a professional geographic computing model agent.
                            Your task is:
                            1. Analyze the user's needs.
                            2. From the 20 candidate models provided below, select the 5 appropriate ones.
                            3. Use the 'recommend_model' tool to return these 5 recommendations.
                            
                            Candidate Models Library:
                            ${JSON.stringify(relevantIndex)}
                            
                            If the request is unrelated to geographic models, do not use the tool.`
            },
            {
                role: 'user',
                content: promt,
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
     * @returns 推荐的5个模型信息
     */
}
