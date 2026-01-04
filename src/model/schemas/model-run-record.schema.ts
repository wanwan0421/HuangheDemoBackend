import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document } from 'mongoose';

export type ModelRunRecordDocument = ModelRunRecord & Document;

@Schema({ timestamps: false })
export class ModelRunRecord {
  @Prop({ required: true, unique: true })
  taskId: string;

  @Prop({ required: true })
  modelName: string;

  @Prop({ required: true })
  jsonPath: string;

  @Prop({ required: true, type: Object })
  states: Record<string, Record<string, any>>;

  @Prop({
    required: true,
    enum: ['Init', 'Started', 'Finished', 'Error'],
    default: 'Init',
  })
  status: string;

  @Prop({ type: Object })
  result?: any;

  @Prop()
  error?: string;

  @Prop({ required: true, default: () => new Date() })
  createdAt: Date;

  @Prop()
  startedAt?: Date;

  @Prop()
  FinishedAt?: Date;
}

export const ModelRunRecordSchema = SchemaFactory.createForClass(ModelRunRecord);
