import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document } from 'mongoose';

export type UserDocument = User & Document;

@Schema({ timestamps: true, collection: 'users' })
export class User {
  @Prop({ required: true, trim: true })
  username!: string;

  @Prop({ required: true, unique: true, lowercase: true, trim: true, index: true })
  email!: string;

  @Prop({ required: true })
  passwordHash!: string;

  @Prop({ type: [Object], default: [] })
  favoriteModels!: Record<string, any>[];

  @Prop({ type: [Object], default: [] })
  favoriteData!: Record<string, any>[];

  @Prop({ type: [Object], default: [] })
  simulationResults!: Record<string, any>[];
}

export const UserSchema = SchemaFactory.createForClass(User);
