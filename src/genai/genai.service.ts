import { Injectable } from '@nestjs/common';
import { GoogleGenAI } from '@google/genai';
import OpenAI from 'openai';
import { ProxyAgent, setGlobalDispatcher } from 'undici';

type GenAIProvider = 'google' | 'openai_compat';

interface ToolCallResult {
    name: string;
    args: Record<string, any>;
}

interface GenerateContentResult {
    functionCalls?: ToolCallResult[];
    text?: string;
}

@Injectable()
export class GenAIService {
    private readonly provider: GenAIProvider;
    private readonly googleClient?: GoogleGenAI;
    private readonly openaiClient?: OpenAI;
    private readonly chatModel: string;
    private readonly embeddingModel: string;
    private readonly embeddingTaskType: string;
    private readonly embeddingBatchSize: number;

    constructor() {
        this.initProxy();
        this.provider = this.resolveProvider();
        this.chatModel = process.env.GENAI_CHAT_MODEL || process.env.CHAT_MODEL || 'gemini-2.5-flash';
        this.embeddingModel = process.env.GENAI_EMBEDDING_MODEL || process.env.EMBEDDING_MODEL || 'gemini-embedding-001';
        this.embeddingTaskType = process.env.GENAI_EMBEDDING_TASK_TYPE || 'RETRIEVAL_DOCUMENT';
        this.embeddingBatchSize = this.resolveEmbeddingBatchSize();

        if (this.provider === 'google') {
            const apiKey = process.env.GENAI_API_KEY || process.env.GOOGLE_API_KEY;
            if (!apiKey) {
                throw new Error('GENAI_API_KEY or GOOGLE_API_KEY must be configured for google provider');
            }
            this.googleClient = new GoogleGenAI({ apiKey });
            return;
        }

        const apiKey =
            process.env.GENAI_API_KEY ||
            process.env.OPENAI_COMPAT_API_KEY ||
            process.env.AIHUBMIX_API_KEY;
        const baseURL =
            process.env.GENAI_BASE_URL ||
            process.env.OPENAI_COMPAT_BASE_URL ||
            process.env.AIHUBMIX_BASE_URL;

        if (!apiKey || !baseURL) {
            throw new Error(
                'GENAI_API_KEY/GENAI_BASE_URL or OPENAI_COMPAT_API_KEY/OPENAI_COMPAT_BASE_URL must be configured for openai_compat provider',
            );
        }

        this.openaiClient = new OpenAI({ apiKey, baseURL });
    }

    private resolveProvider(): GenAIProvider {
        const provider = (process.env.GENAI_PROVIDER || 'google').trim().toLowerCase();
        return provider === 'openai_compat' ? 'openai_compat' : 'google';
    }

    private initProxy() {
        const proxyUrl =
            process.env.GENAI_PROXY_URL ||
            process.env.HTTPS_PROXY ||
            process.env.HTTP_PROXY;
        if (!proxyUrl) {
            return;
        }

        try {
            const dispatcher = new ProxyAgent({
                uri: proxyUrl,
            });
            setGlobalDispatcher(dispatcher);
            console.log('[GenAI] Global Proxy Dispatcher set to:', proxyUrl);
        } catch (err) {
            console.warn('[GenAI] Failed to set proxy:', err);
        }
    }

    private resolveEmbeddingBatchSize(): number {
        const rawValue = process.env.GENAI_EMBEDDING_BATCH_SIZE || process.env.EMBEDDING_BATCH_SIZE;
        const parsed = Number.parseInt(rawValue || '', 10);
        if (Number.isFinite(parsed) && parsed > 0) {
            return parsed;
        }

        // Some DashScope-compatible embedding endpoints reject batches larger than 10.
        return this.provider === 'openai_compat' ? 10 : 100;
    }

    private chunkTexts(texts: string[]): string[][] {
        if (texts.length <= this.embeddingBatchSize) {
            return [texts];
        }

        const chunks: string[][] = [];
        for (let i = 0; i < texts.length; i += this.embeddingBatchSize) {
            chunks.push(texts.slice(i, i + this.embeddingBatchSize));
        }
        return chunks;
    }

    private buildGoogleContents(texts: string[]) {
        return texts.map((text) => ({ parts: [{ text }] }));
    }

    private flattenContents(contents: any): string {
        if (typeof contents === 'string') {
            return contents;
        }

        if (Array.isArray(contents)) {
            return contents
                .map((item) => {
                    if (typeof item === 'string') {
                        return item;
                    }

                    const role = typeof item?.role === 'string' ? item.role : 'user';
                    const parts = Array.isArray(item?.parts)
                        ? item.parts
                              .map((part: any) => (typeof part?.text === 'string' ? part.text : ''))
                              .filter(Boolean)
                              .join('\n')
                        : '';

                    return parts ? `${role}: ${parts}` : '';
                })
                .filter(Boolean)
                .join('\n\n');
        }

        return String(contents ?? '');
    }

    private buildOpenAITools(tool: any) {
        if (!tool) {
            return undefined;
        }

        return [
            {
                type: 'function' as const,
                function: {
                    name: tool.name,
                    description: tool.description,
                    parameters: tool.parameters,
                },
            },
        ];
    }

    async generateEmbeddings(texts: string[]): Promise<number[][]> {
        try {
            if (!Array.isArray(texts) || texts.length === 0) {
                return [];
            }

            if (this.provider === 'google' && this.googleClient) {
                const allEmbeddings: number[][] = [];

                for (const chunk of this.chunkTexts(texts)) {
                    const response = await this.googleClient.models.embedContent({
                        model: this.embeddingModel,
                        contents: this.buildGoogleContents(chunk),
                        config: { taskType: this.embeddingTaskType as any },
                    });

                    const embeddings = response.embeddings
                        ? response.embeddings.map((e) => e.values).filter((v): v is number[] => !!v)
                        : [];

                    if (embeddings.length !== chunk.length) {
                        return [];
                    }

                    allEmbeddings.push(...embeddings);
                }

                return allEmbeddings;
            }

            const allEmbeddings: number[][] = [];
            for (const chunk of this.chunkTexts(texts)) {
                const response = await this.openaiClient!.embeddings.create({
                    model: this.embeddingModel,
                    input: chunk,
                });

                const embeddings = response.data.map((item) => item.embedding);
                if (embeddings.length !== chunk.length) {
                    return [];
                }

                allEmbeddings.push(...embeddings);
            }

            return allEmbeddings;
        } catch (e) {
            console.error('Embedding error', e);
            return [];
        }
    }

    async generateEmbedding(text: string): Promise<number[]> {
        try {
            if (this.provider === 'google' && this.googleClient) {
                const response = await this.googleClient.models.embedContent({
                    model: this.embeddingModel,
                    contents: text,
                    config: { taskType: this.embeddingTaskType as any },
                });
                return response.embeddings?.[0]?.values || [];
            }

            const response = await this.openaiClient!.embeddings.create({
                model: this.embeddingModel,
                input: text,
            });

            return response.data[0]?.embedding || [];
        } catch (e) {
            console.error('Embedding error', e);
            return [];
        }
    }

    async generateContent(contents: any, tool: any): Promise<GenerateContentResult> {
        if (this.provider === 'google' && this.googleClient) {
            const response = await this.googleClient.models.generateContent({
                model: this.chatModel,
                contents,
                config: tool
                    ? {
                          tools: [
                              {
                                  functionDeclarations: [tool],
                              },
                          ],
                      }
                    : undefined,
            });

            return {
                functionCalls: response.functionCalls
                    ?.filter((call) => typeof call.name === 'string' && call.name.length > 0)
                    .map((call) => ({
                        name: call.name as string,
                        args: (call.args as Record<string, any>) || {},
                    })),
                text: typeof response.text === 'string' ? response.text : undefined,
            };
        }

        const response = await this.openaiClient!.chat.completions.create({
            model: this.chatModel,
            messages: [
                {
                    role: 'user',
                    content: this.flattenContents(contents),
                },
            ],
            tools: this.buildOpenAITools(tool),
        });

        const message = response.choices[0]?.message;
        return {
            functionCalls: message?.tool_calls
                ?.filter((call) => call.type === 'function')
                .map((call) => ({
                    name: call.function.name,
                    args: JSON.parse(call.function.arguments || '{}'),
                })),
            text: message?.content || undefined,
        };
    }
}
