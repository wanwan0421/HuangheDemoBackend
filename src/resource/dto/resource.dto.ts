import { IsString,IsNotEmpty, IsOptional, IsEnum } from "class-validator";

// Define resource types
export enum ResourceType {
    MODEL = 'MODEL',
    DATA = 'DATA',
    METHOD = 'METHOD',
}

// define the IO structure for Resource
class ResourceIO {
    @IsString()
    name: string;

    @IsString()
    type: string;
}

export class ResourceDto {
    @IsString()
    @IsNotEmpty()
    id: string;

    @IsEnum(ResourceType)
    type: ResourceType;

    @IsString()
    @IsNotEmpty()
    name: string;

    @IsString()
    @IsOptional()
    description: string;

    input_requirements:ResourceIO[];
    output_requirements:ResourceIO[];

    // URL of external call
    @IsString()
    @IsNotEmpty()
    external_url: string
}