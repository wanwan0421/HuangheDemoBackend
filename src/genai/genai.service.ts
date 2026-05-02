// genai.service.ts
import { Injectable } from '@nestjs/common';
import { GoogleGenAI } from '@google/genai';
import { ProxyAgent, setGlobalDispatcher } from 'undici';

@Injectable()
export class GenAIService {
    private client: GoogleGenAI;

    constructor() {
        this.initProxy();
        this.client = new GoogleGenAI({ apiKey: process.env.GOOGLE_API_KEY });
    }

    private initProxy() {
        const proxyUrl = process.env.HTTPS_PROXY || process.env.HTTP_PROXY || "http://127.0.0.1:7890";
        try {
            const dispatcher = new ProxyAgent({ 
                uri: proxyUrl,
            });
            setGlobalDispatcher(dispatcher);
            console.log("🚀 [GenAI] Global Proxy Dispatcher set to:", proxyUrl);
        } catch (err) {
            console.warn("⚠️ [GenAI] Failed to set proxy:", err);
        }
    }

    /**
     * 将文字转换为数字向量
     * @param texts 文本内容
     * @returens 返回的文本向量数值
     */
    async generateEmbeddings(texts: string[]): Promise<number[][]> {
        try {
            const response = await this.client.models.embedContent({
                model: 'gemini-embedding-001',
                contents: texts.map(text => ({ parts: [{ text }] })),
                config: { taskType: 'RETRIEVAL_DOCUMENT' }
            });

            console.log('[GenAI] embedContent response:', JSON.stringify(response, null, 2));

            const embeddings = response.embeddings
                ? response.embeddings.map(e => e.values).filter((v): v is number[] => !!v)
                : [];

            console.log('[GenAI] Extracted embeddings count:', embeddings.length);
            return embeddings;
        } catch (e) {
            console.error('Embedding error', e);
            return [];
        }
    }

    async generateEmbedding(text: string): Promise<number[]> {
        try {
            const response = await this.client.models.embedContent({
                model: 'gemini-embedding-001',
                contents: text,
                config: { taskType: 'RETRIEVAL_DOCUMENT' }
            });
            return response.embeddings?.[0]?.values || [];
        } catch (e) {
            console.error('Embedding error', e);
            return [];
        }
    }

    async generateContent(contents: any, tool: any) {
        return this.client.models.generateContent({
            model: 'gemini-2.5-flash',
            contents,
            config: {
                tools: [{
                    functionDeclarations: [tool],
                }],
            },
        });
    }

}