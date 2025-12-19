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
                // 如果代理证书有问题，可以取消下面行的注释（生产环境慎用）
                // requestOptions: { rejectUnauthorized: false }
            });
            setGlobalDispatcher(dispatcher);
            console.log("🚀 [GenAI] Global Proxy Dispatcher set to:", proxyUrl);
        } catch (err) {
            console.warn("⚠️ [GenAI] Failed to set proxy:", err.message);
        }
    }

    // 实现 OnModuleInit 钩子，在模块初始化时测试连接
    async onModuleInit() {
        console.log('🧪 [GenAI] Testing network connectivity...');
        try {
            // 测试是否能触达 Google
            await fetch('https://www.google.com', { method: 'HEAD' });
            console.log('✅ [GenAI] Network check passed (Google is reachable)');
        } catch (e) {
            console.error('❌ [GenAI] Network check failed. Your proxy might not be working.');
        }
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