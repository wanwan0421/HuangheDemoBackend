// define the DTO structure and validation for the Controller layer of receiving client requsests and responding
import { IsString,IsNotEmpty, IsOptional, IsEnum } from "class-validator";
import { Type } from "class-transformer";

// the paramter of model resource
export class ModelItemParamDto {
    // 参数名称
    @IsString()
    @IsNotEmpty()
    name: string;

    // 参数类型
    @IsString()
    @IsNotEmpty()
    type: string;

    // 参数描述
    @IsString()
    @IsOptional()
    description?: string;
}
