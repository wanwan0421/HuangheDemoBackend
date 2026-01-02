import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { HttpModule } from '@nestjs/axios';
import { ChatController } from './chat.controller';
import { ChatService } from './chat.service';
import { Session, SessionSchema } from './schemas/session.schema';
import { Message, MessageSchema } from './schemas/message.schema';

@Module({
  imports: [
    HttpModule,
    MongooseModule.forFeature([
      { name: Session.name, schema: SessionSchema },
      { name: Message.name, schema: MessageSchema },
    ]),
  ],
  controllers: [ChatController],
  providers: [ChatService],
})
export class ChatModule {}
