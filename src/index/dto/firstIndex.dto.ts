import { Type } from "class-transformer";
import { secondIndex } from "./secondIndex.dto"
import { IsString, IsNotEmpty, IsArray, ValidateNested } from "class-validator";

export class firstIndex{
    @IsString()
    @IsNotEmpty()
    category_id: string;

    @IsString()
    @IsNotEmpty()
    category_name: string;

    @IsArray()
    @ValidateNested({ each: true })
    @Type(() => secondIndex)
    indicators: secondIndex[] = []; 
}