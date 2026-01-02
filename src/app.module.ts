import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { ResourceModule } from './resource/resource.module';
import { MongooseModule } from '@nestjs/mongoose';
import { ScheduleModule } from '@nestjs/schedule';
import { LlmAgentModule } from './llm-agent/llm-agent.module';
import { IndexModule } from './index/index.module';
import { GenAIModule } from './genai/genai.module';
import { ChatModule } from './chat/chat.module';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: '.env',
    }),
    MongooseModule.forRootAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: async (configService: ConfigService) => ({
        uri: configService.get<string>('mongodbUrl'),
      }),
    }),
    ScheduleModule.forRoot(),
    ResourceModule,
    LlmAgentModule,
    IndexModule,
    GenAIModule,
    ChatModule],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule { }
