import { Prop, Schema, SchemaFactory } from "@nestjs/mongoose";

@Schema({ timestamps: true })
export class ModelEmbedding {

    @Prop({ required: true, index: true })
    modelMd5: string;

    @Prop({ required: true })
    modelName: string;

    @Prop()
    modelDescription: string;

    @Prop({ index: true })
    indicatorEnName: string;

    @Prop({ index: true })
    indicatorCnName: string;

    @Prop({ index: true })
    categoryEnName: string;

    @Prop({ index: true })
    categoryCnName: string;

    @Prop({ index: true })
    sphereEnName: string;

    @Prop({ index: true })
    sphereCnName: string;

    @Prop({ type: [Number], required: true })
    embedding: number[];
}

export const ModelEmbeddingSystemSchema = SchemaFactory.createForClass(ModelEmbedding);