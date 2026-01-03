import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument, Types } from 'mongoose';
import { Session } from './session.schema';
import { ToolDto } from '../dto/tool.dto';

export type MessageDocument = HydratedDocument<Message>;

@Schema({ timestamps: true })
export class Message {
    @Prop({ type: Types.ObjectId, ref: Session.name, index: true })
    sessionId: Types.ObjectId;

    @Prop({ required: true, enum: ['user', 'AI'] })
    role: 'user' | 'AI';

    @Prop({ required: true })
    content: string;

    @Prop({ type: Object })
    tools?: ToolDto[];

    @Prop({ default: Date.now })
    timestamp: Date;

    @Prop({ type: Object })
    recommendedModel?: {
        name: string;
        description: string;
        workflow: any[];
    };
}

export const MessageSchema = SchemaFactory.createForClass(Message);
