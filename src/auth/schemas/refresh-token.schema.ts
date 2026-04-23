import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document, Types } from 'mongoose';

export type RefreshTokenDocument = RefreshToken & Document;

@Schema({ timestamps: true, collection: 'refresh_tokens' })
export class RefreshToken {
  @Prop({ type: Types.ObjectId, required: true, index: true, ref: 'User' })
  userId!: Types.ObjectId;

  @Prop({ required: true, index: true })
  refreshTokenHash!: string;

  @Prop({ required: true })
  expiresAt!: Date;

  @Prop({ type: Date, default: null })
  revokedAt?: Date | null;

  @Prop({ default: '' })
  userAgent?: string;

  @Prop({ default: '' })
  ip?: string;
}

export const RefreshTokenSchema = SchemaFactory.createForClass(RefreshToken);
