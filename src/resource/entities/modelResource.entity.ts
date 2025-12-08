import { Entity, PrimaryColumn, Column, CreateDateColumn, UpdateDateColumn } from 'typeorm';
import { IsArray, ValidateNested } from "class-validator";
import { Type } from "class-transformer";
import { ModelItemParamDto } from "../dto/modelResourceIO.dto";
import { ModelItemDataDto } from "../dto/modelItemData.dto";

export enum ResourceType {
    MODEL = 'MODEL',
    METHOD = 'METHOD',
}

@Entity('modelResource')
export class ModelResource {
    // 基础属性
    @PrimaryColumn()
    id: string; // 模型id

    @Column()
    name: string; // 模型名称

    @Column({ nullable: true })
    description?: string; // 模型描述

    @Column({ nullable: true })
    author?: string; // 模型作者

    @Column({ nullable: true })
    image?: string; // 模型图片

    @Column({ default: "" })
    problemTags: string = ""; // 地理问题标签

    @Column("simple-array", { nullable: true })
    normalTags?: string[]; // 地理问题常规标签

    @Column({ default: true })
    publicBoolean: boolean = true; // 是否公开

    @Column( { type:"enum", enum: ResourceType, default: ResourceType.MODEL } )
    type: ResourceType; // 资源类型：模型方法或数据方法

    // 模型方法属性
    @Column({ nullable: true })
    md5?: string; // 模型文件md5值

    @Column({ type: "text", nullable: true })
    mdl?: string; // 模型的mdl xml直接存储为string

    @Column({ type: "jsonb", nullable: true })
    mdlJson?: Record<string, any>; // 模型的mdl json对象存储
    
    @Type(() => ModelItemDataDto)
    @ValidateNested()
    @Column({ type: "jsonb", nullable: true })
    data?: ModelItemDataDto;

    // 数据方法属性
    @Column({ nullable: true })
    uuid?: string; // 数据方法的uuid

    @Type(() => ModelItemParamDto)
    @IsArray()
    @ValidateNested({ each: true })
    @Column({ type: "jsonb", nullable: true })
    params?: ModelItemParamDto[];

    @Type(() => ModelItemParamDto)
    @IsArray()
    @ValidateNested({ each: true })
    @Column({ type: "jsonb", nullable: true })
    inputParams?: ModelItemParamDto[];

    @Type(() => ModelItemParamDto)
    @IsArray()
    @ValidateNested({ each: true })
    @Column({ type: "jsonb", nullable: true })
    outputParams?: ModelItemParamDto[];

    // 模型绑定的测试数据
    @Column({ type: "jsonb", nullable: true })
    testDataList?: Record<string, any>[] = [];

    // 图像存储属性
    @Column({ nullable: true })
    imgStoreName?: string;
    @Column({ nullable: true })
    imgWebAddress?: string;
    @Column({ nullable: true })
    imgRelativePath?: string;

    // 时间
    @CreateDateColumn({ type: 'timestamptz' })
    createTime?: Date;
    @UpdateDateColumn({ type: 'timestamptz' })
    updateTime?: Date; 
}