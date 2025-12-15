import { Type } from "class-transformer";
import { secondIndexModel } from "./secondIndexModel.dto"
import { IsString, IsNotEmpty, IsArray, ValidateNested } from "class-validator";

export class secondIndex{
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

    @IsArray()
    @ValidateNested({ each: true })
    @Type(() => secondIndexModel)
    models: secondIndexModel[] = []; 
}