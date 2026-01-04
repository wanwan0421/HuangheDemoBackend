import { Module } from '@nestjs/common';
import { MongooseModule } from '@nestjs/mongoose';
import { ModelRunnerController } from './model.controller';
import { ModelRunnerService } from './model.service';
import { ModelRunRecord, ModelRunRecordSchema } from './schemas/model-run-record.schema';

@Module({
  imports: [
    MongooseModule.forFeature([
      { name: ModelRunRecord.name, schema: ModelRunRecordSchema },
    ]),
  ],
  controllers: [ModelRunnerController],
  providers: [ModelRunnerService],
})
export class ModelRunnerModule {}
