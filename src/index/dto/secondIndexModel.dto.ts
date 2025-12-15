import { IsNotEmpty, IsString } from "class-validator"

export class secondIndexModel {
    @IsString()
    @IsNotEmpty()
    modelId: string;

    @IsString()
    @IsNotEmpty()
    modelName: string;

    @IsString()
    @IsNotEmpty()
    modelInput: string;

    @IsString()
    @IsNotEmpty()
    modelOutput: string;
}