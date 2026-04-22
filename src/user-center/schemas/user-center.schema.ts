import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document } from 'mongoose';

export type UserCenterDocument = UserCenter & Document;

@Schema({ timestamps: true, collection: 'user_center' })
export class UserCenter {
  @Prop({ required: true, unique: true, index: true })
  userId!: string;

  @Prop({ type: [Object], default: [] })
  favoriteModels!: Record<string, any>[];

  @Prop({ type: [Object], default: [] })
  favoriteData!: Record<string, any>[];

  @Prop({ type: [Object], default: [] })
  simulationResults!: Record<string, any>[];
}

export const UserCenterSchema = SchemaFactory.createForClass(UserCenter);
