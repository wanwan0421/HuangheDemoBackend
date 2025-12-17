import { Type } from "class-transformer";
import { thirdIndexModel } from "./thirdIndexModel.dto"
import { IsString, IsNotEmpty, IsArray, ValidateNested } from "class-validator";
import { Prop } from "@nestjs/mongoose";

export class thirdIndex{
    @IsString()
    @IsNotEmpty()
    code: string;

    @IsString()
    @IsNotEmpty()
    name_en: string;

    @IsString()
    @IsNotEmpty()
    name_cn: string;

    @IsString()
    @IsNotEmpty()
    field_name: string;

    @Prop({ type: [thirdIndexModel] })
    @IsArray()
    @ValidateNested({ each: true })
    @Type(() => thirdIndexModel)
    models: thirdIndexModel[] = []; 
}