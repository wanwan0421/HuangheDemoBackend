import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { ResourceModule } from './resource/resource.module';

@Module({
  imports: [ResourceModule],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
