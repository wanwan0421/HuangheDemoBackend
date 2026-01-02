import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument } from 'mongoose';

export type SessionDocument = HydratedDocument<Session>;

@Schema({ timestamps: true })
export class Session {
  @Prop({ required: true })
  title: string;

  @Prop()
  userId?: string;

  @Prop({ default: 0 })
  messageCount: number;

  @Prop()
  lastMessage?: string;

  @Prop({ default: Date.now })
  createdAt: Date;

  @Prop({ default: Date.now })
  updatedAt: Date;
}

export const SessionSchema = SchemaFactory.createForClass(Session);
