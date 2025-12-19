// genai.service.ts
import { Injectable } from '@nestjs/common';
import { GoogleGenAI } from '@google/genai';

@Injectable()
export class GenAIService {
    private client: GoogleGenAI;

    constructor() {
        this.client = new GoogleGenAI({ apiKey: process.env.GOOGLE_API_KEY });
    }

    /**
     * 将文字转换为数字向量
     * @param text 文本内容
     * @returens 返回的文本向量数值
     */
    async generateEmbedding(text: string): Promise<number[]> {
        try {
            const response = await this.client.models.embedContent({
                model: 'gemini-embedding-001',
                contents: text,
                config: { taskType: 'RETRIEVAL_QUERY' }
            });
            return response.embeddings?.[0]?.values || [];
        } catch (e) {
            console.error('Embedding error', e);
            return [];
        }
    }

    async generateContent(params: any) {
        return this.client.models.generateContent(params);
    }
}