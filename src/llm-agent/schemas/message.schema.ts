import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document, Types } from 'mongoose';

export type MessageDocument = Message & Document;

@Schema({ timestamps: true })
export class Message {
  @Prop({ type: Types.ObjectId, ref: 'Session', required: true, index: true })
  sessionId: Types.ObjectId;

  @Prop({ required: true, enum: ['user', 'assistant', 'system'] })
  role: string;

  @Prop({ required: true })
  content: string;

  @Prop({ type: Object })
  tools?: any[];

  @Prop({ default: Date.now })
  timestamp: Date;
}

export const MessageSchema = SchemaFactory.createForClass(Message);
