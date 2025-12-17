import { Type } from "class-transformer";
import { thirdIndex } from "./thirdIndex.dto"
import { IsString, IsNotEmpty, IsArray, ValidateNested } from "class-validator";

export class secondIndex{
    @IsString()
    @IsNotEmpty()
    category_id: string;

    @IsString()
    @IsNotEmpty()
    category_name: string;

    @IsArray()
    @ValidateNested({ each: true })
    @Type(() => thirdIndex)
    indicators: thirdIndex[] = []; 
}