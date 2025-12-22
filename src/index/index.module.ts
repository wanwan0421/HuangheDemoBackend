import { Module } from '@nestjs/common';
import { IndexService } from './index.service';
import { IndexController } from './index.controller';
import { HttpModule } from '@nestjs/axios';
import { MongooseModule } from '@nestjs/mongoose';
import { indexSystem, IndexSystemSchema } from './schemas/index.schema';
import { ModelEmbedding, ModelEmbeddingSystemSchema } from './schemas/modelEmbedding.schema';
import { GenAIModule } from 'src/genai/genai.module';

@Module({
  imports: [
    HttpModule,
    MongooseModule.forFeature([{ name: indexSystem.name, schema: IndexSystemSchema }]),
    MongooseModule.forFeature([{ name: ModelEmbedding.name, schema: ModelEmbeddingSystemSchema }]),
    GenAIModule
  ],
  providers: [IndexService],
  controllers: [IndexController],
  exports: [IndexService]
})
export class IndexModule {}
