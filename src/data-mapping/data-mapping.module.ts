import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { DataMappingController } from './data-mapping.controller';
import { DataMappingService } from './data-mapping.service';
import { Session, SessionSchema } from '../chat/schemas/session.schema';
import { Message, MessageSchema } from '../chat/schemas/message.schema';

@Module({
  imports: [
    MongooseModule.forFeature([
      { name: Session.name, schema: SessionSchema },
      { name: Message.name, schema: MessageSchema },
    ]),
  ],
  controllers: [DataMappingController],
  providers: [DataMappingService]
})
export class DataMappingModule {}
