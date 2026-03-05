import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument } from 'mongoose';

export type DataScanResultDocument = HydratedDocument<DataScanResult>;

@Schema({ timestamps: true, collection: 'dataScanResults' })
export class DataScanResult {
  @Prop({ required: true, index: true })
  sessionId: string;

  @Prop({ required: true })
  filePath: string;

  @Prop({ default: '' })
  scanResult: string;

  @Prop({ type: Array, default: [] })
  tools: any[];

  @Prop({ type: Object })
  profile?: any;

  @Prop({ required: true, enum: ['completed', 'interrupted'] })
  status: 'completed' | 'interrupted';

  @Prop()
  errorMessage?: string;
}

export const DataScanResultSchema = SchemaFactory.createForClass(DataScanResult);
