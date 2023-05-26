/**
 * @file main_optimized.c
 * @author Homin Kang (hmkang4110@gmail.com)
 * @brief ADL Detector (DEAN Node) environmental signal generator
 * @version 0.1
 * @date 2023-05-12
 * 
 * @copyright Copyright (c) 2023
 * 
 */

#include "pthread_msgq_main.h"
#include "type_definitions.h"

typedef struct _msgq_recv_data_t{
    long data_type;
    // int data_num;
    unsigned char data_buff[MSGQ_DATA_BUFF_SIZE];
} msgq_recv_data_t;

typedef struct _sensor_value_t{
    int val_int;
    int val_dec;
} sensor_value_t;

FILE *data_fp = NULL;



/** FUNCTIONS **/
void sig_handler(int signo)
{
    printf("[SIGNAL] process stop\n");
    if(data_fp != NULL)
    {
        fclose(data_fp);
        printf("[SIGNAL] file close done\n");
    }
    exit(0);
}

/**
 * @brief 
 * 
 * @param data 
 * @return void* 
 */
void *from_python_to_c_thread_func(void * data)
{
    // init parameters
    char file_save_dir[100] = {0,};
    char file_data_write_buff[FILE_BUFF_SIZE] = {0,};
    char file_data_read_buff[FILE_BUFF_SIZE] = {0,};
    unsigned int SerialIndex = 0;
    // MSGQ parameters
    int msgq_id;
    msgq_recv_data_t recv_adl_data;
    memset(&recv_adl_data, 0, sizeof(msgq_recv_data_t));
    if ( -1 == (msgq_id = msgget( (key_t)6604, IPC_CREAT | 0666)))
    {
        perror("msgget() failed");
        exit(1);
    }
    else
    {
        printf("[THREAD] PTYHON_TO_C MSGQ THREAD INIT SUCCESS\n");
    }    

    // pthread loop
    for(;;)
    {
        memset(&recv_adl_data, 0, sizeof(msgq_recv_data_t));
        if ( -1 == msgrcv (msgq_id, &recv_adl_data, sizeof(msgq_recv_data_t) - sizeof(long) , 0, 0))
        {
            perror("[RECV THREAD] msgrcv failed\n");
            exit(1);
        }

        // datetime handling and open file named "yyyy.mm.dd.dat"
        time_t time_unix_sec;
        struct tm *datetime;
        time(&time_unix_sec);
        datetime = (struct tm*)localtime(&time_unix_sec);
        sprintf(file_save_dir, "./data/%04d.%02d.%02d.dat", 1900+datetime->tm_year, 1+datetime->tm_mon, datetime->tm_mday);
        if (data_fp == NULL)
        {
            data_fp = fopen(file_save_dir, "a+");
            printf("[FILE] : fopen success : %p\n", data_fp);
            sprintf(file_data_write_buff, ";SignalType,SerialIndex,time,HomeOwner,Location,press,temp,humid,gas_raw,iaq,s_iaq,eco2,bvoc,gas_percent,clear,Action,Type\n");
            int result = fputs(file_data_write_buff, data_fp);
            if (result == EOF)
            {
                printf("[FILE] file printing error : %d\n", result);
            }
        }
        else
        {
            // if the file is written first time : set Column name and "I" packet
            fseek(data_fp, 0, SEEK_END);
            if(ftell(data_fp) == 0)
            {
                sprintf(file_data_write_buff, ";SignalType,SerialIndex,time,HomeOwner,Location,press,temp,humid,gas_raw,iaq,s_iaq,eco2,bvoc,gas_percent,clear,Action,Type\n");
                int result = fputs(file_data_write_buff, data_fp);
                if (result == EOF)
                {
                    printf("[FILE] file printing error : %d\n", result);
                }
            }
            // if the file exists and there is data to be written
            else
            {
                memset(file_data_read_buff, 0, sizeof(file_data_read_buff));
                memset(file_data_write_buff, 0, sizeof(file_data_write_buff));
            }
        }

        // Parsing receiving MSGs from Python-MSGQ
        switch(recv_adl_data.data_type)
        {
            case MSGQ_TYPE_DEVICE:
            {
                printf("[THREAD] TYPE DEVICE received\n");
                char file_write_data[FILE_BUFF_SIZE+10];
                sprintf(file_write_data, "D,%d,%04d-%02d-%02d %02d:%02d:%02d,", 
                                        SerialIndex,
                                        1900+datetime->tm_year, 1+datetime->tm_mon, datetime->tm_mday, datetime->tm_hour, datetime->tm_min, datetime->tm_sec);
                strcat(file_write_data, recv_adl_data.data_buff);
                if (EOF == fputs(file_write_data, data_fp))
                {
                    printf("[FILE] file writing error\n");
                }
                memset(file_data_write_buff, 0, sizeof(file_data_write_buff));
                break;
            }
            case MSGQ_TYPE_ENV:
            {
                sensor_value_t sensor_value[9];
                memcpy(&sensor_value, &recv_adl_data.data_buff, sizeof(sensor_value));
                // sensor_value_t press, temp, humid, gas_raw, iaq, s_iaq, eco2, bvoc, gas_percent;
                printf("[THREAD] TYPE ENV received\n");
                // Write received data to file
                // SignalType,SerialIndex,Datetime, HomeOwner,Location,press,temp,humid,gas_raw,iaq,s_iaq,eco2,bvoc,gas_percent,clear,Action,Type
                sprintf(file_data_write_buff, "E,%d,%04d-%02d-%02d %02d:%02d:%02d,%s,%s,%d.%d,%d.%d,%d.%d,%d.%d,%d.%d,%d.%d,%d.%d,%d.%d,%d.%d\n",
                                            SerialIndex,1900+datetime->tm_year, 1+datetime->tm_mon, datetime->tm_mday, datetime->tm_hour, datetime->tm_min, datetime->tm_sec,
                                            "HMK","Toilet",
                                            sensor_value[0].val_int, sensor_value[0].val_dec,
                                            sensor_value[1].val_int, sensor_value[1].val_dec,
                                            sensor_value[2].val_int, sensor_value[2].val_dec,
                                            sensor_value[3].val_int, sensor_value[3].val_dec,
                                            sensor_value[4].val_int, sensor_value[4].val_dec,
                                            sensor_value[5].val_int, sensor_value[5].val_dec,
                                            sensor_value[6].val_int, sensor_value[6].val_dec,
                                            sensor_value[7].val_int, sensor_value[7].val_dec,
                                            sensor_value[8].val_int, sensor_value[8].val_dec);
                if (EOF == fputs(file_data_write_buff, data_fp))
                {
                    printf("[FILE] file writing error\n");
                }
                memset(file_data_write_buff, 0, sizeof(file_data_write_buff));
                break;
            }
            case MSGQ_TYPE_SOUND:
            {
                printf("[THREAD] TYPE SOUND received\n");
                char file_write_data[FILE_BUFF_SIZE+10];
                sprintf(file_write_data, "S,%d,%04d-%02d-%02d %02d:%02d:%02d,", 
                                        SerialIndex,
                                        1900+datetime->tm_year, 1+datetime->tm_mon, datetime->tm_mday, datetime->tm_hour, datetime->tm_min, datetime->tm_sec);
                strcat(file_write_data, recv_adl_data.data_buff);
                if (EOF == fputs(file_write_data, data_fp))
                {
                    printf("[FILE] file writing error\n");
                }
                memset(file_data_write_buff, 0, sizeof(file_data_write_buff));
                break;
            }
        }
        SerialIndex++;
    } // end of pthread loop

    return 0;
}

int main()
{
    // init parameters
    // MSGQ parameters
    int msgq_id;
    msgq_recv_data_t recv_adl_data;
    pthread_t env_data_msgq_thread_t;
    int pthread_status;

    signal(SIGINT, (void *)sig_handler);

    printf("[MAIN] ENV signal generator initiating...\n");
    // main loop
    // Pthread create
    if (pthread_create(&env_data_msgq_thread_t, NULL, from_python_to_c_thread_func, NULL) < 0)
    {
        perror("[MAIN] thread create error\n");
        exit(1);
    }

    // wait pthread end (never happens)
    pthread_join(env_data_msgq_thread_t, (void **)pthread_status);
    printf("[MAIN] End of main --> what happens? Something error!\n");

    return 0;
}