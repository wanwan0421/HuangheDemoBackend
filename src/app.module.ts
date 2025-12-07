import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { ConfigModule } from '@nestjs/config';
import { ResourceModule } from './resource/resource.module';

@Module({
  imports: [ConfigModule.forRoot({
    isGlobal: true,
    envFilePath: '.env',
  }),
  ResourceModule],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
