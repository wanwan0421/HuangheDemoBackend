import { Module } from '@nestjs/common';
import { IndexService } from './index.service';
import { IndexController } from './index.controller';
import { HttpModule } from '@nestjs/axios';
import { MongooseModule } from '@nestjs/mongoose';
import { index, IndexSystemSchema } from './schemas/index.schema';
import { GenAIModule } from 'src/genai/genai.module';

@Module({
  imports: [
    HttpModule,
    MongooseModule.forFeature([{ name: index.name, schema: IndexSystemSchema }]),
    GenAIModule
  ],
  providers: [IndexService],
  controllers: [IndexController],
  exports: [IndexService]
})
export class IndexModule {}
