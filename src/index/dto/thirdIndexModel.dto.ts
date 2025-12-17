import { IsArray, IsNotEmpty, IsString } from "class-validator"

export class thirdIndexModel {
    @IsString()
    @IsNotEmpty()
    model_id: string;

    @IsString()
    @IsNotEmpty()
    model_name: string;

    @IsString()
    @IsNotEmpty()
    model_input: string;

    @IsString()
    @IsNotEmpty()
    model_output: string;

    @IsArray()
    @IsNotEmpty()
    field_name: string[];

    @IsString()
    @IsNotEmpty()
    primary_indicator: string;
}