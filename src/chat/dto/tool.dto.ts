import { IsString, IsNotEmpty, IsOptional } from "class-validator";

// 定义AI返回工具事件类型
export class ToolDto {
    @IsString()
    @IsNotEmpty()
    id: string;

    @IsString()
    @IsNotEmpty()
    status: string;

    @IsString()
    @IsNotEmpty()
    title: string;

    @IsString()
    @IsNotEmpty()
    kind: string;

    @IsOptional()
    result?: any;
}