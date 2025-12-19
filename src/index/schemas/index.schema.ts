import { Prop, Schema, SchemaFactory } from "@nestjs/mongoose";
import { secondIndex } from "../dto/secondIndex.dto";

@Schema({ collection: 'index' })
export class index{
    @Prop({ required: true, index: true })
    sphere_id: string;  // 圈层id: 英文名

    @Prop({ required: true })
    sphere_name: string; // 圈层名称

    @Prop()
    sphere_order: number; // 排序

    @Prop({ type: Array })
    categories: secondIndex[] = [];
}

export const IndexSystemSchema = SchemaFactory.createForClass(index);