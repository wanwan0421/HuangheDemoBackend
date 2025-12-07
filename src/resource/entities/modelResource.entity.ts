import { IsArray, ValidateNested } from "class-validator";
import { Type } from "class-transformer";
import { ModelItemParamDto } from "../dto/modelResourceIO.dto";
import { ModelItemDataDto } from "../dto/modelItemData.dto";

export enum ResourceType {
    MODEL = 'MODEL',
    METHOD = 'METHOD',
}

export class ModelResource {
    // 基础属性
    id: string; // 模型id
    name: string; // 模型名称
    description?: string; // 模型描述
    author?: string; // 模型作者
    image?: string; // 模型图片
    problemTags: string = ""; // 地理问题标签
    normalTags?: string[]; // 地理问题常规标签
    publicBoolean: boolean = true; // 是否公开
    type: ResourceType; // 资源类型：模型方法或数据方法

    // 模型方法属性
    md5?: string; // 模型文件md5值
    mdl?: string; // 模型的mdl xml直接存储为string
    mdlJson?: Record<string, any>; // 模型的mdl json对象存储
    
    @Type(() => ModelItemDataDto)
    @ValidateNested()
    data?: ModelItemDataDto[];

    // 数据方法属性
    uuid?: string; // 数据方法的uuid

    @Type(() => ModelItemParamDto)
    @IsArray()
    @ValidateNested({ each: true })
    params?: ModelItemParamDto[];

    @Type(() => ModelItemParamDto)
    @IsArray()
    @ValidateNested({ each: true })
    inputParams?: ModelItemParamDto[];

    @Type(() => ModelItemParamDto)
    @IsArray()
    @ValidateNested({ each: true })
    outputParams?: ModelItemParamDto[];

    // 模型绑定的测试数据
    testDataList?: Record<string, any>[] = [];

    // 图像存储属性
    imgStoreName?: string;
    imgWebAddress?: string;
    imgRelativePath?: string;

    // 时间
    createTime?: Date;
    updateTime?: Date; 
}