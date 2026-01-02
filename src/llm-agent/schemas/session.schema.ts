import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document } from 'mongoose';

export type SessionDocument = Session & Document;

@Schema({ timestamps: true })
export class Session {
  @Prop({ required: true })
  title: string;

  @Prop({ default: Date.now })
  createdAt: Date;

  @Prop({ default: Date.now })
  updatedAt: Date;

  @Prop()
  userId?: string;

  @Prop({ default: 0 })
  messageCount: number;

  @Prop()
  lastMessage?: string;
}

export const SessionSchema = SchemaFactory.createForClass(Session);
