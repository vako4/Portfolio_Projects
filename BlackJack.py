#!/usr/bin/env python
# coding: utf-8

# In[1]:


import random
cards = [11,2,3,4,5,6,7,8,9,10,10,10,10]

start_game = input("Do you want to play game of blackjack? type y/n ").lower()



def win_or_lose(your_sum,comp_sum):
  if your_sum > 21:
        print("You lose")  
  else:
    if comp_sum > your_sum:
      print("You lose")
    elif comp_sum < your_sum or your_sum == 21:
      print("You win")
    else:
      print("Draw")

end = False


if start_game == "y":
  your_cards = (random.sample(cards,k = 2))
  print(f"Your cards: {your_cards}")
  comp_cards = (random.sample(cards,k = 2))
  print(f"Computers first card: {comp_cards[0]}")
  while end == False:
    if sum(your_cards) == 21:
      end = True
      print("Your sum is 21, You win
    else:
      hit_stand = input("Type y to get another card, type n to pass ").lower()
      if hit_stand == "y":
        your_cards.append(random.choice(cards))
        your_sum = sum(your_cards)
        comp_sum = sum(comp_cards)
        
        if your_sum > 21:
          if 11 in your_cards:
            your_cards.remove(11)
            your_cards.append(1)
            print(f"Your cards: {your_cards}, score: {sum(your_cards)}")
          else:
            end = True
            print(f"Your cards: {your_cards}, final score: {your_sum}")
            print("You Lose")
        elif your_sum == 21:
          end = True
          print(f"Your cards: {your_cards}, final score: {your_sum}")
          print(f"Computer's cards: {comp_cards}, final score: {comp_sum}")
          print("You Win")  
        else:
          print(f"Your cards: {your_cards} score: {your_sum}")
          print(f"Computers first card: {comp_cards[0]}")
      elif hit_stand == "n":
        end = True
        your_sum = sum(your_cards)
        while sum(comp_cards) < 17:
          comp_cards.append(random.choice(cards))
        comp_sum = sum(comp_cards)  
        print(f"Your cards: {your_cards}, final score: {your_sum}")
        print(f"Computer's cards: {comp_cards}, final score: {comp_sum}")
        win_or_lose(your_sum,comp_sum)

