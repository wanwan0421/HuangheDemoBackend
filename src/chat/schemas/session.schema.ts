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

    @Prop({ type: Object })
    recommendedModel?: {
        name: string;
        description: string;
        workflow: any[];
    };

    @Prop({ type: Object })
    profile?: any;

    @Prop({ type: Object })
    taskSpec?: any;

    @Prop({ type: Object })
    modelContract?: any;

    @Prop({ type: Object })
    alignmentResult?: any;

    @Prop()
    alignmentStatus?: string;

    @Prop()
    goNoGo?: string;

    @Prop()
    canRunNow?: boolean;

    @Prop({ type: Object })
    context?: any;
}

export const SessionSchema = SchemaFactory.createForClass(Session);
