import { Module } from '@nestjs/common';
import { IndexService } from './index.service';
import { IndexController } from './index.controller';
import { HttpModule } from '@nestjs/axios';
import { MongooseModule } from '@nestjs/mongoose';
import { IndexSystem, IndexSystemSchema } from './schemas/index.schema';

@Module({
  imports: [
    HttpModule,
    MongooseModule.forFeature([{ name: IndexSystem.name, schema: IndexSystemSchema }])
  ],
  providers: [IndexService],
  controllers: [IndexController]
})
export class IndexModule {}
