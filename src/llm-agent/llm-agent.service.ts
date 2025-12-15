import { Injectable } from '@nestjs/common';
import { GoogleGenAI, Type } from '@google/genai';
import { LlmRecommendationModelName } from './interfaces/llmRecommendationModelName.interface';
import { modelRecommendationTool } from './schemas/llmTools.schema';

@Injectable()
export class LlmAgentService {

    /**
     * 调用LLM API，使用结构化输出获取模型推荐
     * @param promt 用户输入
     * @returens 推荐的模型信息
     */
    private async callLLMForRecommendation(promt: string): Promise<LlmRecommendationModelName | null> {
        const ai = new GoogleGenAI({});

        const contents = [
            {
                role: 'system',
                content: 'You are a professional geographic computing model agent. Your task is to analyze the needs of users and select the most appropriate model from the model library for recommendation. Do not use tools if user requirements are not related to the geographic model.'
            },
            {
                role: 'user',
                content: promt,
            }
        ];

        try {
            const response = await ai.models.generateContent({
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
                    const functionCallArgs = functionCall.args;

                    const name = functionCallArgs?.['name'] as string;
                    const reason = functionCallArgs?.['reason'] as string;

                    if (name) {
                        return {
                            name: name,
                            reason: reason
                        }
                    }
                }

            }
            return null;
        } catch (error) {
            return null;
        }
    }
}
