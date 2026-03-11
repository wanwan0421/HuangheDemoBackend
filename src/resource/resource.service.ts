import { Injectable, Logger } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { InjectModel } from '@nestjs/mongoose';
import { Model, Document } from 'mongoose';
import { ConfigService } from '@nestjs/config';
import { plainToInstance } from 'class-transformer';
import { ModelResource, ResourceType } from './schemas/modelResource.schema';
import { ModelEmbedding } from '../index/schemas/modelEmbedding.schema';
import { Md5Item, OnePageMd5Result, PortalMd5Data } from './interfaces/portalSync.interface';
import { firstValueFrom } from 'rxjs';
import { ModelItemDataDto } from './dto/modelItemData.dto';
import { ModelItemStateDto } from './dto/modelItemState.dto';
import { ModelUtilsService } from './modelUtils.service';
import { ModelItemEventDataDto } from './dto/modelItemEventData.dto';
import { ModelItemEventDataNodeDto } from './dto/modelItemEventDataNode.dto';
import { ModelItemEventDto } from './dto/modelItemEvent.dto';
import { GenAIService } from 'src/genai/genai.service';
import { Cron, CronExpression } from '@nestjs/schedule';

@Injectable()
export class ResourceService {
    private readonly logger = new Logger(ResourceService.name); // 日志记录器
    private readonly portalLocation: string;
    private readonly portalToken: string;
    private readonly pageSize = 20;
    private readonly embeddingSource = 'resource-sync';

    constructor(private readonly httpService: HttpService,
                private readonly configService: ConfigService,
                private readonly modelUtilsService: ModelUtilsService,
                private readonly genAIService: GenAIService,
                @InjectModel(ModelResource.name)
                private modelResourceModel: Model<ModelResource>,
                @InjectModel(ModelEmbedding.name)
                private ModelEmbeddingModel: Model<ModelEmbedding & Document>,
    ) {
        this.portalLocation = this.configService.get<string>('portalLocation')!;
        this.portalToken = this.configService.get<string>('portalToken')!;
    }

    async onModuleInit() {
        console.log('🚀 正在初始化模型向量数据...');
        try {
            await this.initResourceModelVectorData();
            console.log('✅ 模型向量初始化完成');
        } catch (error) {
            console.error('❌ 模型向量初始化失败:', error);
        }
    }

    // 获取单页健康模型的md5列表
    // @param page 页码
    // @param pageSize 每页数量
    private async getHealthyModelMd5List(page: number, pageSize: number): Promise<OnePageMd5Result> {
        const url = `http://${this.portalLocation}/managementSystem/deployedModel?${this.portalToken}`;

        const body = {
            asc: false,
            page: page,
            pageSize: pageSize,
            searchText: '',
            sortField: 'viewCount'
        }

        // 发送GET请求并接收ResonseEntity
        try {
            // 取Observable第一次输出的值作为Promise结果
            // Observable = 可持续产生数据的“数据流”
            const response = await firstValueFrom(
                this.httpService.post<any>(url, body)
            )

            if (response.status !== 200 || !response.data) {
                this.logger.error(`Failed to fetch data from portal, status: ${response.status}`);
                throw new Error(`Failed to fetch data from portal, status: ${response.status}`);
            }

            const dataNode: PortalMd5Data = response.data.data;
            const md5List = dataNode.content.map((item: Md5Item) => item.md5);

            return {
                totalNumber: dataNode.total,
                md5List: md5List
            };
        } catch (error) {
            this.logger.error(`Error fetching data from portal: ${error}`);
            throw new Error(`Error fetching data from portal: ${error}`);
        }
    }

    // 循环获取门户所有模型的MD5列表
    private async getPortalModelMd5(): Promise<string[]> {
        const pageSize = this.pageSize;
        let onePageMd5 = await this.getHealthyModelMd5List(1, pageSize);
        const modelsMd5List: string[] = [...onePageMd5.md5List];

        const totalModels = onePageMd5.totalNumber;
        const totalPages = Math.ceil(totalModels / pageSize);

        for (let page = 2; page <= totalPages; page++) {
            try {
                onePageMd5 = await this.getHealthyModelMd5List(page, pageSize);
                modelsMd5List.push(...onePageMd5.md5List);
            } catch (error) {
                this.logger.error(`Error fetching data from portal on page ${page}: ${error}`);
                continue;
            }
        }
        return modelsMd5List;
    }

    // 主入口：获取门户模型并同步到本地
    // 每小时更新一次
    @Cron(CronExpression.EVERY_DAY_AT_1AM)
    public async synchronizePortalModels(): Promise<void> {
        console.log("Start synchronizing portal models...");
        const modelsMd5List = await this.getPortalModelMd5();
        const baseUrl = `http://${this.portalLocation}/computableModel/ModelInfoAndClassifications_pid/`;

        // 遍历MD5列表，逐个获取模型详情并保存
        for (const md5 of modelsMd5List) {
            try {
                const detailResponse = await firstValueFrom(
                    this.httpService.get<any>(baseUrl + md5)
                )

                if (detailResponse.status !== 200 || !detailResponse.data) {
                    throw new Error(`Failed to fetch model details for md5 ${md5}, status: ${detailResponse.status}`);
                }

                const modelData = detailResponse.data.data;
                // 将mdl的XML转换为JSON对象
                const mdlJson = await this.modelUtilsService.convertMdlXmlToJson(modelData.mdl);

                // 获取mdl中的states
                const statesJson = mdlJson['mdl']?.states;
                // 获取mdl中的data
                const modelItemData = this.getModelItemData(statesJson);

                // 解析最后修改时间
                const updateTime = modelData.lastModifyTime;

                const newModel: Partial<ModelResource> = {
                    name: modelData.name,
                    id: modelData.id,
                    description: modelData.overview,
                    author: modelData.author,

                    normalTags: modelData.itemClassifications,
                    type: ResourceType.MODEL,
                    md5: modelData.md5,
                    mdl: modelData.mdl,
                    mdlJson: mdlJson,
                    data: modelItemData,
                    updateTime: updateTime,
                };

                await this.saveModel(newModel);

            } catch (error) {
                this.logger.error(`Error processing model with md5 ${md5}: ${error}`);
            }
        }

        try {
            await this.initResourceModelVectorData();
        } catch (error) {
            this.logger.error(`Error synchronizing model embeddings: ${error}`);
        }
    }

    // 从解析后的MDL中的states中提取输入/输出数据结构
    // @param statesJson 经过MDL解析后的States JSON数组
    public getModelItemData(states: Record<string, any>[] | null | undefined): ModelItemDataDto {
        const inputStates: ModelItemStateDto[] = [];
        const outputStates: ModelItemStateDto[] = [];

        if (states && Array.isArray(states)) {
            for (const state of states) {
                const { input, output } = this.getModelItemStates(state);
                inputStates.push(input);
                outputStates.push(output);
            }
        }

        // 转换为顶层 ModelItemDataDto 实例
        return plainToInstance(ModelItemDataDto, {
            input: inputStates,
            output: outputStates
        });
    }

    // 从解析后的MDL中提取states流程
    private getModelItemStates(state: Record<string, any>): { input: ModelItemStateDto, output: ModelItemStateDto } {
        const inputEvents: ModelItemEventDto[] = [];
        const outputEvents: ModelItemEventDto[] = [];

        const events = state.event;
        if (events && Array.isArray(events)) {
            for (const event of events) {
                const modelItemEvent = this.getModelItemEvents(event);

                // 根据eventType区分输入输出事件
                if (modelItemEvent.eventType === "response") {
                    inputEvents.push(modelItemEvent);
                } else {
                    outputEvents.push(modelItemEvent);
                }
            } 
        }

        // 组合state对象
        const statePlain = {
            stateName: state.stateName,
            stateDescription: state.stateDesc,
        };

        // 创建inputState DTO实例
        const inputStateDto = plainToInstance(ModelItemStateDto, {
            ...statePlain,
            events: inputEvents
        });

        // 创建outputState DTO实例
        const outputStateDto = plainToInstance(ModelItemStateDto, {
            ...statePlain,
            events: outputEvents
        });

        return { input: inputStateDto, output: outputStateDto };
    }

    // 从解析后的MDL中的states中提取events事件
    private getModelItemEvents(event: Record<string, any>): ModelItemEventDto {
        // 需要手动处理optional字段，因为有些JSON中不存在该字段
        let optional = false;
        if (event.optional !== undefined && event.optional !== null) {
            optional = !!event.optional;
        }

        // 递归获取Event事件中的数据
        const eventData = this.getModelItemEventData(event.data);

        // 组合event对象
        const eventPlain = {
            eventName: event.eventName,
            eventDescription: event.eventDesc,
            eventType: event.eventType,
            optional: optional,
            eventData: eventData,
        }

        // 转换为ModelItemEventDto实例并返回
        return plainToInstance(ModelItemEventDto, eventPlain);
    }

    // 从解析后的MDL中的states中提取event事件中使用的data细节结构
    private getModelItemEventData(dataArr: any[] | null | undefined): ModelItemEventDataDto | null {
        if (!dataArr || !Array.isArray(dataArr) || dataArr.length === 0) {
            return null;
        }

        const eventData = dataArr[0]; // 目前只处理第一个data节点
        // 手动处理nodes列表（因为nodes字段在MDL的JSON结构中是ModelItemEventData的子字段）
        let nodeList: ModelItemEventDataNodeDto[] = [];
        if (eventData.nodes && Array.isArray(eventData.nodes)) {
            // 转换每个node为ModelItemEventDataNodeDto实例，其中第一个参数为类构造函数，第二个参数为数组
            nodeList = plainToInstance<ModelItemEventDataNodeDto, any[]>(ModelItemEventDataNodeDto, eventData.nodes);
        }

        // 组合eventData对象
        const eventDataPlain = {
            eventDataType: eventData.type,
            eventDataName: eventData.name,
            exentDataDesc: eventData.description,
            nodeList: nodeList
        };

        // 转换为ModelItemEventDataDto实例并返回
        return plainToInstance(ModelItemEventDataDto, eventDataPlain);
    }

    // 将解析和转换后的ModelResource保存到数据库
    // @param modelData 包含模型数据的Partial<ModelResource>对象
    private async saveModel(modelData: Partial<ModelResource>): Promise<ModelResource> {
        const updateData = {
            // 使用$set确保只更新提供的字段
            $set: {  ...modelData }
        };

        try {
            // 使用fineOneAndUpdate实现upsert操作
            const result = await this.modelResourceModel.findOneAndUpdate(
                { id: modelData.id }, // 查找条件
                updateData,          // 更新数据
                { new: true, upsert: true } // 选项：返回更新后的文档，若不存在则创建新文档
            ).exec();

            return result;
        } catch (error) {
            throw new Error(`Error saving model ${modelData.id}: ${error}`);
        }
    }

    // 前端根据关键词或者分类查询模型资源列表
    public async findModels(filter: { categoryId?: string[]; keyword?: string}): Promise<ModelResource[]> {
        const { categoryId, keyword } = filter;
        const query: any = {type: ResourceType.MODEL};

        // 根据分类过滤
        if (categoryId?.length !== 0) {
            query.normalTags = { $in: categoryId } // 使用 $in 操作符查找normalTags数组中包含任一指定ID(类别)的资源

        }

        // 根据关键字查找
        if (keyword) {
            const regex = new RegExp(keyword, 'i') //'i'表示不区分大小写

            // 使用 $or 组合名称和描述的模糊匹配条件
            const keywordQuery = {
                $or: [
                    { name: { $regex: regex }},
                    { description: { $regex: regex }},
                ]
            }

            Object.assign(query, keywordQuery);
        }

        try {
            const results = await this.modelResourceModel.find(query).exec();

            return results;
        } catch(error) {
            throw new Error("Faild to fetch model resources.");
        }
    }

    // 用于返回指标对应的单个模型的详细信息
    public async getModelDetails(md5: string): Promise<ModelResource | null> {
        return this.modelResourceModel.findOne({ md5: md5 }).lean().exec();
    }

    /**
     * 遍历modelResourceModel数据库将"模型名称+模型描述"拼接为一段话为每个模型生成embedding并存入到ModelEmbeddingModel
     */
    private normalizeText(value: unknown): string {
        return typeof value === 'string' ? value : '';
    }

    private async upsertResourceEmbeddings(
        tasks: Array<{
            modelId: string;
            modelMd5: string;
            modelName: string;
            modelDescription: string;
        }>,
        activeModelIds: string[],
        activeModelMd5s: string[],
    ): Promise<void> {
        const dedupedTaskMap = new Map<string, {
            modelId: string;
            modelMd5: string;
            modelName: string;
            modelDescription: string;
        }>();

        for (const task of tasks) {
            if (!task.modelId || !task.modelMd5) {
                continue;
            }
            dedupedTaskMap.set(task.modelId, task);
        }

        const dedupedTasks = Array.from(dedupedTaskMap.values());

        if (dedupedTasks.length > 0) {
            const CHUNK_SIZE = 50;
            for (let i = 0; i < dedupedTasks.length; i += CHUNK_SIZE) {
                try {
                    const chunk = dedupedTasks.slice(i, i + CHUNK_SIZE);
                    const texts = chunk.map((task) =>
                        `model_name: ${task.modelName}. model_description: ${task.modelDescription}.`,
                    );

                    const vectors = await this.genAIService.generateEmbeddings(texts);

                    if (!vectors || !Array.isArray(vectors) || vectors.length !== chunk.length) {
                        this.logger.error(`⚠️ 批次索引 ${i} 失败：API 返回数据无效或受限。跳过此批次。`);
                        await new Promise((resolve) => setTimeout(resolve, 60000));
                        continue;
                    }

                    const writeOperations = chunk.map((task, index) => ({
                        updateOne: {
                            filter: {
                                $or: [
                                    { modelId: task.modelId },
                                    { modelMd5: task.modelMd5, embeddingSource: this.embeddingSource },
                                ],
                            },
                            update: {
                                $set: {
                                    modelId: task.modelId,
                                    modelMd5: task.modelMd5,
                                    modelName: task.modelName,
                                    modelDescription: task.modelDescription,
                                    embeddingSource: this.embeddingSource,
                                    embedding: vectors[index],
                                },
                            },
                            upsert: true,
                        },
                    }));

                    await this.ModelEmbeddingModel.bulkWrite(writeOperations, { ordered: false });
                    await new Promise((resolve) => setTimeout(resolve, 30000));
                } catch (error) {
                    this.logger.error(`处理模型向量批次（起始索引 ${i}）时出错: ${error}`);
                }
            }
        } else {
            this.logger.log('没有检测到需要更新的模型向量。');
        }

        if (activeModelIds.length === 0 && activeModelMd5s.length === 0) {
            this.logger.warn('门户模型列表为空，跳过向量清理。');
            return;
        }

        await this.ModelEmbeddingModel.deleteMany({
            embeddingSource: this.embeddingSource,
            $or: [
                { modelId: { $exists: true, $nin: activeModelIds } },
                { modelId: { $exists: false }, modelMd5: { $nin: activeModelMd5s } },
            ],
        }).exec();
    }

    public async initResourceModelVectorData() {
        const data = await this.modelResourceModel
            .find({}, { id: 1, md5: 1, name: 1, description: 1 })
            .lean();
        console.log(`查找到 ${data.length} 条模型资源数据`);

        await this.ModelEmbeddingModel.updateMany(
            {
                embeddingSource: { $exists: false },
                indicatorEnName: { $exists: false },
                categoryEnName: { $exists: false },
                sphereEnName: { $exists: false },
            },
            {
                $set: { embeddingSource: this.embeddingSource },
            },
        ).exec();

        const existingEmbeddingDocs = await this.ModelEmbeddingModel
            .find(
                { embeddingSource: this.embeddingSource },
                { modelId: 1, modelMd5: 1, modelName: 1, modelDescription: 1, embedding: 1 },
            )
            .lean();

        const embeddingByModelId = new Map<string, any>();
        for (const item of existingEmbeddingDocs) {
            const modelId = this.normalizeText(item.modelId);
            if (modelId) {
                embeddingByModelId.set(modelId, item);
            }
        }

        const activeModelIds: string[] = [];
        const activeModelMd5s: string[] = [];
        const modelTasks: Array<{
            modelId: string;
            modelMd5: string;
            modelName: string;
            modelDescription: string;
        }> = [];

        for (const model of data) {
            const modelId = this.normalizeText(model.id);
            if (!modelId) {
                continue;
            }

            activeModelIds.push(modelId);

            const modelMd5 = this.normalizeText(model.md5);
            if (modelMd5) {
                activeModelMd5s.push(modelMd5);
            }

            if (!modelMd5) {
                continue;
            }

            const modelName = this.normalizeText(model.name);
            const modelDescription = this.normalizeText(model.description);
            const existingEmbedding = embeddingByModelId.get(modelId);
            const hasValidVector =
                existingEmbedding &&
                Array.isArray(existingEmbedding.embedding) &&
                existingEmbedding.embedding.length > 0;

            const needRefresh =
                !hasValidVector ||
                this.normalizeText(existingEmbedding.modelMd5) !== modelMd5 ||
                this.normalizeText(existingEmbedding.modelName) !== modelName ||
                this.normalizeText(existingEmbedding.modelDescription) !== modelDescription;

            if (!needRefresh) {
                continue;
            }

            modelTasks.push({
                modelId,
                modelMd5,
                modelName,
                modelDescription,
            });
        }

        await this.upsertResourceEmbeddings(modelTasks, activeModelIds, activeModelMd5s);
        console.log(`✅ 资源模型向量同步完成，本次更新 ${modelTasks.length} 条`);
    }
}
