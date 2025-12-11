import { HydratedDocument } from "mongoose";
import { Prop, Schema, SchemaFactory } from "@nestjs/mongoose";
import { ModelItemDataDto } from "../dto/modelItemData.dto";
import { ModelItemParamDto } from "../dto/modelResourceIO.dto";

export enum ResourceType {
    MODEL = "MODEL",
    METHOD = "METHOD"
}

// 定义Mongoose Document的类型
export type ModelResourceDocument = HydratedDocument<ModelResource>;

@Schema({ 
    timestamps: { createdAt: 'createTime', updatedAt: false},
    collection: 'modelResource'
})
export class ModelResource {
    // 基础属性
    @Prop({ unique: true, required: true, index: true })
    id: string; // 模型id

    @Prop({ required: true })
    name: string; // 模型名称

    @Prop()
    description?: string; // 模型描述

    @Prop()
    author?: string; // 模型作者

    @Prop()
    image?: string; // 模型图片

    @Prop({ default: "" })
    problemTags: string = ""; // 地理问题标签

    @Prop({ type: [String] })
    normalTags?: string[]; // 地理问题常规标签

    @Prop({ default: true })
    publicBoolean: boolean = true; // 是否公开

    @Prop({ type: String, enum: ResourceType, default: ResourceType.MODEL })
    type: ResourceType; // 资源类型：模型方法或数据方法

    // 模型方法属性
    @Prop({ required: true, index: true })
    md5?: string; // 模型文件md5值

    @Prop({ type: String })
    mdl?: string; // 模型的mdl xml直接存储为string

    @Prop({ type: Object })
    mdlJson?: Record<string, any>; // 模型的mdl json对象存储

    @Prop({ type: Object })
    data?: ModelItemDataDto;

    // 数据方法属性
    @Prop()
    uuid?: string; // 数据方法的uuid

    // @Prop({ type: [Object] })
    // params?: ModelItemParamDto[];

    // @Prop({ type: [Object] })
    // inputParams?: ModelItemParamDto[];

    // @Prop({ type: [Object] })
    // outputParams?: ModelItemParamDto[];

    // 模型绑定的测试数据
    @Prop({ type: [Object], default: [] })
    testDataList?: Record<string, any>[] = [];

    // 图像存储属性
    @Prop()
    imgStoreName?: string;
    @Prop()
    imgWebAddress?: string;
    @Prop()
    imgRelativePath?: string;

    @Prop({ type: Date })
    updateTime?: Date;
}

export const ModelResourceSchema = SchemaFactory.createForClass(ModelResource);