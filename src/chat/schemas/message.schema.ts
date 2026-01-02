import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument, Types } from 'mongoose';
import { Session } from './session.schema';

export type MessageDocument = HydratedDocument<Message>;

@Schema({ timestamps: true })
export class Message {
  @Prop({ type: Types.ObjectId, ref: Session.name, index: true })
  sessionId: Types.ObjectId;

  @Prop({ required: true, enum: ['user', 'assistant', 'system'] })
  role: 'user' | 'assistant' | 'system';

  @Prop({ required: true })
  content: string;

  @Prop({ type: Object })
  tools?: any;

  @Prop({ default: Date.now })
  timestamp: Date;
}

export const MessageSchema = SchemaFactory.createForClass(Message);
